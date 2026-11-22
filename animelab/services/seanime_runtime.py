"""Execution runtime for Seanime JavaScript/TypeScript extensions.

Runs transpiled Seanime providers inside an isolated V8 sandbox (`mini-racer`
on Desktop/Docker/Linux/macOS/Windows, or offscreen `WebView` V8 via
``SeanimeJsBridge`` on Android) while routing all outbound HTTP traffic through
AnimeLab's SSRF-protected :mod:`animelab.services.source_http` transport.
"""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
import json
import logging
import sys
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from animelab.security import is_safe_url, is_safe_url_async
from animelab.services.seanime_ts import prepare_extension_source
from animelab.services.source_http import VerificationRequired, source_http

logger = logging.getLogger(__name__)

_SHIM_FILENAME = "seanime_shim.js"
_MAX_FETCH_BYTES = 16 * 1024 * 1024


class SeanimeRuntimeError(RuntimeError):
    """Error raised when a Seanime provider execution fails."""

    def __init__(self, message: str, *, logs: list[str] | None = None, stack: str = "") -> None:
        super().__init__(message)
        self.logs = list(logs or [])
        self.stack = stack


class SeanimeSyntaxError(SeanimeRuntimeError):
    """Raised when TypeScript transpilation or V8 compilation fails."""


@lru_cache(maxsize=1)
def load_shim_source() -> str:
    """Return the shared JS shim code bundled alongside this module."""
    direct = Path(__file__).with_name(_SHIM_FILENAME)
    if direct.is_file():
        return direct.read_text(encoding="utf-8")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "animelab" / "services" / _SHIM_FILENAME
        if bundled.is_file():
            return bundled.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Impossible de trouver {_SHIM_FILENAME}")


def _sanitize_header_param(name: str) -> str:
    return name.replace("\r", "").replace("\n", "").replace('"', "")


def _build_multipart_body(fields: list[Any]) -> tuple[bytes, str]:
    boundary = f"----AnimeLabSeanimeBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for entry in fields:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            name = _sanitize_header_param(str(entry[0]))
            value = str(entry[1] if entry[1] is not None else "")
        elif isinstance(entry, dict):
            name = _sanitize_header_param(str(entry.get("name") or ""))
            value = str(entry.get("value") if entry.get("value") is not None else "")
        else:
            continue
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _prepare_request_args(req: dict[str, Any]) -> tuple[str, str, dict[str, str], float, bool, str, bytes | None]:
    url = str(req.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"URL invalide ou protocole interdit : {url}")

    method = str(req.get("method") or "GET").upper()
    raw_headers = req.get("headers") or {}
    headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        for k, v in raw_headers.items():
            if k is not None and v is not None:
                headers[str(k)] = str(v)

    try:
        timeout = float(req.get("timeout") or 35.0)
    except (TypeError, ValueError):
        timeout = 35.0
    timeout = min(max(timeout, 1.0), 90.0)

    redirect_mode = str(req.get("redirect") or "follow").lower()
    follow_redirects = redirect_mode == "follow"

    content: bytes | None = None
    if req.get("bodyEncoding") == "formdata":
        content, ct = _build_multipart_body(list(req.get("formFields") or []))
        headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        headers["Content-Type"] = ct
    elif req.get("bodyBase64"):
        content = base64.b64decode(str(req["bodyBase64"]))
    elif req.get("bodyText") is not None:
        content = str(req["bodyText"]).encode("utf-8")
        declared_ct = req.get("contentType")
        if declared_ct and not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = str(declared_ct)

    return url, method, headers, timeout, follow_redirects, redirect_mode, content


def _is_textual_content(content_type: str, payload: bytes) -> bool:
    lowered = content_type.lower()
    if any(
        token in lowered
        for token in (
            "text/",
            "json",
            "xml",
            "javascript",
            "ecmascript",
            "x-www-form-urlencoded",
            "svg+xml",
            "mpegurl",
        )
    ):
        return True
    if any(token in lowered for token in ("image/", "video/", "audio/", "octet-stream", "pdf", "zip")):
        return False
    if b"\x00" in payload[:1024]:
        return False
    try:
        payload[:4096].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _serialize_response(response: httpx.Response, method: str, request_url: str, redirect_mode: str) -> dict[str, Any]:
    if redirect_mode == "error" and response.status_code in (301, 302, 303, 307, 308):
        return {"error": f"Redirection interdite par fetch(redirect='error') : {response.status_code}"}

    headers_dict: dict[str, str] = {}
    raw_headers: dict[str, list[str]] = {}
    items = response.headers.multi_items() if hasattr(response.headers, "multi_items") else response.headers.items()
    for key, val in items:
        key_str = str(key)
        val_str = str(val)
        headers_dict[key_str] = val_str
        raw_headers.setdefault(key_str, []).append(val_str)

    cookies_dict: dict[str, str] = {}
    try:
        for name, value in response.cookies.items():
            cookies_dict[str(name)] = str(value)
    except Exception:
        pass
    try:
        state = source_http.state(str(response.url))
        for cookie in state.cookies:
            if not cookie.is_expired():
                cookies_dict.setdefault(str(cookie.name), str(cookie.value))
    except Exception:
        pass

    content_type = response.headers.get("content-type", "")
    raw_bytes = response.content or b""
    is_text = _is_textual_content(content_type, raw_bytes)
    payload: dict[str, Any] = {
        "status": int(response.status_code),
        "statusText": str(getattr(response, "reason_phrase", "") or ""),
        "method": method,
        "ok": 200 <= response.status_code < 300,
        "url": str(response.url),
        "redirected": str(response.url) != request_url,
        "headers": headers_dict,
        "rawHeaders": raw_headers,
        "cookies": cookies_dict,
        "contentType": content_type,
        "contentLength": len(raw_bytes),
    }
    if is_text:
        payload["bodyText"] = raw_bytes.decode("utf-8", errors="replace")
    else:
        payload["bodyBase64"] = base64.b64encode(raw_bytes).decode("ascii")
    return payload


def _ssrf_guard_sync(url: str) -> None:
    if not is_safe_url(url, allow_private=False):
        raise ValueError(f"URL bloquée par la protection SSRF : {url}")


def apply_user_config_placeholders(
    source: str,
    user_config: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> str:
    """Substitute declared ``{{fieldName}}`` placeholders using saved config or defaults."""
    if not source or "{{" not in source:
        return source
    merged: dict[str, str] = {}
    if defaults:
        for k, v in defaults.items():
            if k:
                merged[str(k)] = "" if v is None else str(v)
    if user_config:
        for k, v in user_config.items():
            if k and v is not None and str(v) != "":
                merged[str(k)] = str(v)
    if not merged:
        return source
    out = source
    for key, val in merged.items():
        token = f"{{{{{key}}}}}"
        if token in out:
            out = out.replace(token, val)
    return out


async def host_fetch_json(
    req_json_str: str,
    *,
    client_factory: Callable[..., Any] | None = None,
    on_verification: Callable[[VerificationRequired], None] | None = None,
    max_timeout: float | None = None,
) -> str:
    """Execute one JS ``fetch()`` call via AnimeLab's SSRF-protected transport."""
    try:
        req = json.loads(req_json_str) if req_json_str else {}
        if not isinstance(req, dict):
            raise ValueError("Requête fetch invalide")
        url, method, headers, timeout, follow_redirects, redirect_mode, content = _prepare_request_args(req)
        if max_timeout is not None:
            timeout = max(1.0, min(timeout, float(max_timeout)))
        if not await is_safe_url_async(url, allow_private=False):
            return json.dumps({"error": f"URL bloquée par la protection SSRF : {url}"})

        request_kwargs: dict[str, Any] = {"headers": headers}
        if content is not None:
            request_kwargs["content"] = content

        if client_factory is not None:
            async with client_factory(follow_redirects=follow_redirects, headers=headers, timeout=timeout) as client:
                response = await client.request(method, url, timeout=timeout, **request_kwargs)
        else:
            if method in ("GET", "HEAD"):
                request_kwargs["max_response_bytes"] = _MAX_FETCH_BYTES
            async with source_http.async_client(
                follow_redirects=follow_redirects,
                timeout=timeout,
                url_validator=_ssrf_guard_sync,
            ) as client:
                response = await client.request(method, url, **request_kwargs)

        if len(response.content or b"") > _MAX_FETCH_BYTES:
            return json.dumps({"error": "La réponse dépasse la taille autorisée."})
        return json.dumps(_serialize_response(response, method, url, redirect_mode))
    except VerificationRequired as exc:
        if on_verification is not None:
            on_verification(exc)
        return json.dumps({"error": str(exc), "verificationRequired": True, "verificationUrl": exc.url})
    except Exception as exc:
        logger.debug("Seanime fetch error: %s", exc)
        return json.dumps({"error": str(exc)})


def host_fetch_json_sync(req_json_str: str) -> str:
    """Synchronous variant used by Android's offscreen WebView IO worker."""
    try:
        req = json.loads(req_json_str) if req_json_str else {}
        if not isinstance(req, dict):
            raise ValueError("Requête fetch invalide")
        url, method, headers, timeout, follow_redirects, redirect_mode, content = _prepare_request_args(req)
        if not is_safe_url(url, allow_private=False):
            return json.dumps({"error": f"URL bloquée par la protection SSRF : {url}"})

        request_kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
        if content is not None:
            request_kwargs["content"] = content

        with source_http.client(
            follow_redirects=follow_redirects,
            timeout=timeout,
            url_validator=_ssrf_guard_sync,
        ) as client:
            response = client.request(method, url, **request_kwargs)

        if len(response.content or b"") > _MAX_FETCH_BYTES:
            return json.dumps({"error": "La réponse dépasse la taille autorisée."})
        return json.dumps(_serialize_response(response, method, url, redirect_mode))
    except VerificationRequired as exc:
        return json.dumps({"error": str(exc), "verificationRequired": True, "verificationUrl": exc.url})
    except Exception as exc:
        logger.debug("Seanime sync fetch error: %s", exc)
        return json.dumps({"error": str(exc)})


class MiniRacerSeanimeRuntime:
    """Isolated V8 runtime backed by ``py_mini_racer``."""

    def __init__(self, *, client_factory: Callable[..., Any] | None = None) -> None:
        self._client_factory = client_factory
        self._stores: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._get_cache: OrderedDict[tuple[Any, ...], tuple[float, str]] = OrderedDict()
        self._inflight_gets: dict[tuple[int, tuple[Any, ...]], asyncio.Task[str]] = {}
        self._get_cache_ttl = 45.0
        self._get_cache_max_entries = 64
        self._get_cache_max_bytes = 2 * 1024 * 1024

    def is_available(self) -> bool:
        try:
            import py_mini_racer  # noqa: F401
            return True
        except Exception:
            return False

    def engine_name(self) -> str:
        return "mini-racer" if self.is_available() else "unavailable"

    def clear_http_cache(self, extension_id: str | None = None) -> None:
        with self._lock:
            if extension_id is None:
                self._get_cache.clear()
                return
            for key in [k for k in self._get_cache if k and k[0] == extension_id]:
                self._get_cache.pop(key, None)

    def clear_store(self, extension_id: str) -> None:
        with self._lock:
            self._stores.pop(extension_id, None)
        self.clear_http_cache(extension_id)

    def get_store(self, extension_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._stores.get(extension_id) or {})

    def set_store(self, extension_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._stores[extension_id] = dict(data)

    def validate_syntax(
        self,
        source: str,
        *,
        language: str = "javascript",
        extension_id: str = "validate",
        user_config: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Transpile (if TypeScript) and compile ``Provider`` inside V8."""
        try:
            rendered = apply_user_config_placeholders(source, user_config, defaults)
            prepared = prepare_extension_source(rendered, language)
        except Exception as exc:
            return False, f"Erreur de transpilation TypeScript : {exc}"

        try:
            from py_mini_racer import mini_racer
        except Exception as exc:
            return False, f"Moteur V8 indisponible : {exc}"

        shim = load_shim_source()
        try:
            with mini_racer() as ctx:
                ctx.eval(shim)
                compile_fn: Any = ctx.eval("globalThis.__seanimeCompile")
                compile_fn(prepared)
            return True, None
        except Exception as exc:
            logger.debug("Seanime syntax validation failed for %s: %s", extension_id, exc)
            return False, str(exc)

    def _get_cached_response(self, cache_key: tuple[Any, ...]) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._get_cache.get(cache_key)
            if entry is None:
                return None
            ts, payload = entry
            if (now - ts) >= self._get_cache_ttl:
                self._get_cache.pop(cache_key, None)
                return None
            self._get_cache.move_to_end(cache_key)
            return payload

    def _put_cached_response(self, cache_key: tuple[Any, ...], raw_json: str) -> None:
        try:
            parsed = json.loads(raw_json)
        except Exception:
            return
        if not isinstance(parsed, dict) or parsed.get("error"):
            return
        if int(parsed.get("status") or 0) != 200:
            return
        if int(parsed.get("contentLength") or 0) > self._get_cache_max_bytes:
            return
        with self._lock:
            self._get_cache[cache_key] = (time.monotonic(), raw_json)
            self._get_cache.move_to_end(cache_key)
            while len(self._get_cache) > self._get_cache_max_entries:
                self._get_cache.popitem(last=False)

    async def invoke(
        self,
        *,
        extension_id: str,
        source: str,
        language: str,
        method: str,
        args: list[Any] | None = None,
        user_config: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        store: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> tuple[Any, dict[str, Any], list[str]]:
        """Compile and invoke a ``Provider`` method asynchronously inside V8."""
        rendered_source = apply_user_config_placeholders(source, user_config, defaults)
        prepared = prepare_extension_source(rendered_source, language)
        shim = load_shim_source()
        initial_store = dict(store) if store is not None else self.get_store(extension_id)
        loop = asyncio.get_running_loop()

        try:
            from py_mini_racer import mini_racer
        except Exception as exc:
            raise SeanimeRuntimeError(f"Moteur V8 indisponible : {exc}") from exc

        verification_error: VerificationRequired | None = None
        deadline = time.monotonic() + float(timeout)

        def _capture_verification(exc: VerificationRequired) -> None:
            nonlocal verification_error
            verification_error = exc

        async def _bridge_fetch(req_json: str) -> str:
            remaining = deadline - time.monotonic()
            if remaining <= 0.25:
                return json.dumps({"error": f"Délai d'exécution Seanime dépassé ({timeout:.0f}s)"})

            cache_key: tuple[Any, ...] | None = None
            if self._client_factory is None:
                try:
                    req_obj = json.loads(req_json) if req_json else {}
                except Exception:
                    req_obj = None
                if isinstance(req_obj, dict):
                    req_method = str(req_obj.get("method") or "GET").upper()
                    req_url = str(req_obj.get("url") or "").strip()
                    raw_headers = req_obj.get("headers") or {}
                    has_auth = isinstance(raw_headers, dict) and any(
                        str(k).lower() == "authorization" for k in raw_headers
                    )
                    if req_method == "GET" and req_url and not has_auth:
                        norm_headers = tuple(
                            sorted(
                                (str(k).lower(), str(v))
                                for k, v in (raw_headers.items() if isinstance(raw_headers, dict) else ())
                                if k is not None and v is not None
                            )
                        )
                        redirect_mode = str(req_obj.get("redirect") or "follow").lower()
                        cache_key = (extension_id, req_url, norm_headers, redirect_mode)
                        cached = self._get_cached_response(cache_key)
                        if cached is not None:
                            return cached

            if cache_key is None:
                return await host_fetch_json(
                    req_json,
                    client_factory=self._client_factory,
                    on_verification=_capture_verification,
                    max_timeout=remaining,
                )

            inflight_key = (id(loop), cache_key)
            task = self._inflight_gets.get(inflight_key)
            if task is None:
                async def _run_cached_get() -> str:
                    try:
                        out = await host_fetch_json(
                            req_json,
                            client_factory=None,
                            on_verification=_capture_verification,
                            max_timeout=remaining,
                        )
                        self._put_cached_response(cache_key, out)
                        return out
                    finally:
                        if self._inflight_gets.get(inflight_key) is task:
                            self._inflight_gets.pop(inflight_key, None)

                task = asyncio.create_task(_run_cached_get())
                self._inflight_gets[inflight_key] = task

            raw_out = await asyncio.shield(task)
            try:
                parsed_out = json.loads(raw_out)
                if isinstance(parsed_out, dict) and parsed_out.get("verificationRequired"):
                    _capture_verification(
                        VerificationRequired(
                            parsed_out.get("verificationUrl") or cache_key[1],
                            parsed_out.get("error") or None,
                        )
                    )
            except Exception:
                pass
            return raw_out

        with mini_racer(event_loop=loop) as ctx:
            async with ctx.wrap_py_function(_bridge_fetch) as js_fetch:
                ctx.eval(shim)
                setter: Any = ctx.eval("(function(fn) { globalThis.__seanimeHostFetch = fn; })")
                setter(js_fetch)
                compile_fn: Any = ctx.eval("globalThis.__seanimeCompile")
                compile_fn(prepared)
                invoke_fn: Any = ctx.eval("globalThis.__seanimeInvoke")

                try:
                    raw_result = await asyncio.wait_for(
                        invoke_fn(
                            method,
                            json.dumps(args or []),
                            json.dumps(user_config or {}),
                            json.dumps(defaults or {}),
                            json.dumps(initial_store),
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError as exc:
                    raise SeanimeRuntimeError(f"Délai d'exécution Seanime dépassé ({timeout:.0f}s)") from exc

        payload = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        if not isinstance(payload, dict):
            raise SeanimeRuntimeError("Réponse invalide du moteur Seanime")

        new_store = dict(payload.get("store") or {})
        self.set_store(extension_id, new_store)
        logs = [str(item) for item in (payload.get("logs") or [])]

        result = payload.get("result")
        empty_result = (
            result is None
            or result == []
            or (isinstance(result, dict) and method == "findEpisodeServer" and not result.get("videoSources"))
        )

        if not payload.get("ok"):
            if verification_error is not None:
                raise verification_error
            raise SeanimeRuntimeError(
                str(payload.get("error") or "Erreur d'exécution Seanime"),
                logs=logs,
                stack=str(payload.get("stack") or ""),
            )

        if verification_error is not None and empty_result:
            raise verification_error

        return result, new_store, logs


class AndroidSeanimeRuntime:
    """Offscreen WebView V8 bridge used when running inside the Android APK."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._stores: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def is_available(self) -> bool:
        try:
            return bool(self._bridge and self._bridge.isAvailable())
        except Exception:
            return False

    def engine_name(self) -> str:
        return "android-webview"

    def clear_http_cache(self, extension_id: str | None = None) -> None:
        return

    def clear_store(self, extension_id: str) -> None:
        with self._lock:
            self._stores.pop(extension_id, None)

    def get_store(self, extension_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._stores.get(extension_id) or {})

    def set_store(self, extension_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._stores[extension_id] = dict(data)

    def validate_syntax(
        self,
        source: str,
        *,
        language: str = "javascript",
        extension_id: str = "validate",
        user_config: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        try:
            rendered = apply_user_config_placeholders(source, user_config, defaults)
            prepared = prepare_extension_source(rendered, language)
        except Exception as exc:
            return False, f"Erreur de transpilation TypeScript : {exc}"
        try:
            raw = str(self._bridge.validateSyntax(load_shim_source(), prepared))
        except Exception as exc:
            return False, str(exc)
        if raw == "ok":
            return True, None
        return False, raw.removeprefix("error:") or "Erreur de syntaxe JS WebView"

    async def invoke(
        self,
        *,
        extension_id: str,
        source: str,
        language: str,
        method: str,
        args: list[Any] | None = None,
        user_config: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        store: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> tuple[Any, dict[str, Any], list[str]]:
        rendered_source = apply_user_config_placeholders(source, user_config, defaults)
        prepared = prepare_extension_source(rendered_source, language)
        initial_store = dict(store) if store is not None else self.get_store(extension_id)
        request_payload = json.dumps(
            {
                "shim": load_shim_source(),
                "code": prepared,
                "method": method,
                "argsJson": json.dumps(args or []),
                "userConfigJson": json.dumps(user_config or {}),
                "defaultsJson": json.dumps(defaults or {}),
                "storeJson": json.dumps(initial_store),
                "timeoutMs": int(timeout * 1000),
            }
        )
        raw_result = await asyncio.to_thread(self._bridge.invoke, request_payload)
        payload = json.loads(str(raw_result))
        if not isinstance(payload, dict):
            raise SeanimeRuntimeError("Réponse invalide de WebView Seanime")

        new_store = dict(payload.get("store") or {})
        self.set_store(extension_id, new_store)
        logs = [str(item) for item in (payload.get("logs") or [])]

        if not payload.get("ok"):
            raise SeanimeRuntimeError(
                str(payload.get("error") or "Erreur WebView Seanime"),
                logs=logs,
                stack=str(payload.get("stack") or ""),
            )
        return payload.get("result"), new_store, logs


class SeanimeRuntimeFacade:
    """Platform-agnostic runtime facade defaulting to MiniRacer or Android WebView."""

    def __init__(self) -> None:
        self._desktop = MiniRacerSeanimeRuntime()
        self._android: AndroidSeanimeRuntime | None = None

    def configure_android(self, bridge: Any | None) -> None:
        self._android = AndroidSeanimeRuntime(bridge) if bridge is not None else None

    @property
    def backend(self) -> MiniRacerSeanimeRuntime | AndroidSeanimeRuntime:
        return self._android if self._android is not None else self._desktop

    def is_available(self) -> bool:
        return self.backend.is_available()

    def engine_name(self) -> str:
        return self.backend.engine_name()

    def clear_http_cache(self, extension_id: str | None = None) -> None:
        self.backend.clear_http_cache(extension_id)

    def clear_store(self, extension_id: str) -> None:
        self.backend.clear_store(extension_id)

    def get_store(self, extension_id: str) -> dict[str, Any]:
        return self.backend.get_store(extension_id)

    def set_store(self, extension_id: str, data: dict[str, Any]) -> None:
        self.backend.set_store(extension_id, data)

    def validate_syntax(
        self,
        source: str,
        *,
        language: str = "javascript",
        extension_id: str = "validate",
        user_config: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        return self.backend.validate_syntax(
            source,
            language=language,
            extension_id=extension_id,
            user_config=user_config,
            defaults=defaults,
        )

    async def invoke(
        self,
        *,
        extension_id: str,
        source: str,
        language: str,
        method: str,
        args: list[Any] | None = None,
        user_config: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        store: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> tuple[Any, dict[str, Any], list[str]]:
        return await self.backend.invoke(
            extension_id=extension_id,
            source=source,
            language=language,
            method=method,
            args=args,
            user_config=user_config,
            defaults=defaults,
            store=store,
            timeout=timeout,
        )


seanime_runtime = SeanimeRuntimeFacade()
