"""Execution runtime for Seanime JavaScript/TypeScript extensions.

Runs transpiled Seanime providers inside an isolated V8 sandbox (`mini-racer`
on Desktop/Docker/Linux/macOS/Windows, or offscreen `WebView` V8 via
``SeanimeJsBridge`` on Android) while routing all outbound HTTP traffic through
AnimeLab's SSRF-protected :mod:`animelab.services.source_http` transport.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import threading
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


async def host_fetch_json(
    req_json_str: str,
    *,
    client_factory: Callable[..., Any] | None = None,
    on_verification: Callable[[VerificationRequired], None] | None = None,
) -> str:
    """Execute one JS ``fetch()`` call via AnimeLab's SSRF-protected transport."""
    try:
        req = json.loads(req_json_str) if req_json_str else {}
        if not isinstance(req, dict):
            raise ValueError("Requête fetch invalide")
        url, method, headers, timeout, follow_redirects, redirect_mode, content = _prepare_request_args(req)
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

    def is_available(self) -> bool:
        try:
            import py_mini_racer  # noqa: F401
            return True
        except Exception:
            return False

    def engine_name(self) -> str:
        return "mini-racer" if self.is_available() else "unavailable"

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
    ) -> tuple[bool, str | None]:
        """Transpile (if TypeScript) and compile ``Provider`` inside V8."""
        try:
            prepared = prepare_extension_source(source, language)
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
        prepared = prepare_extension_source(source, language)
        shim = load_shim_source()
        initial_store = dict(store) if store is not None else self.get_store(extension_id)
        loop = asyncio.get_running_loop()

        try:
            from py_mini_racer import mini_racer
        except Exception as exc:
            raise SeanimeRuntimeError(f"Moteur V8 indisponible : {exc}") from exc

        verification_error: VerificationRequired | None = None

        def _capture_verification(exc: VerificationRequired) -> None:
            nonlocal verification_error
            verification_error = exc

        async def _bridge_fetch(req_json: str) -> str:
            return await host_fetch_json(
                req_json,
                client_factory=self._client_factory,
                on_verification=_capture_verification,
            )

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
    ) -> tuple[bool, str | None]:
        try:
            prepared = prepare_extension_source(source, language)
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
        prepared = prepare_extension_source(source, language)
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
    ) -> tuple[bool, str | None]:
        return self.backend.validate_syntax(source, language=language, extension_id=extension_id)

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
