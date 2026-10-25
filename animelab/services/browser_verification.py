"""User-assisted verification in an installed browser; no browser downloads."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from urllib.parse import urlparse

import httpx
import websockets

from animelab.services.verification_platform import ChromiumVerification, WebViewVerification
from animelab.security import is_safe_url
from animelab.services.source_http import source_http, VerificationRequired


class BrowserVerificationService:
    def __init__(self, transport=source_http):
        self.transport = transport
        self.jobs = {}
        self.webview_opener = None
        self.platform = "desktop"
        self.mechanisms = {"browser": ChromiumVerification(), "webview": WebViewVerification()}
        self._lock = asyncio.Lock()

    def installed_browsers(self):
        candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                      "microsoft-edge", "microsoft-edge-stable", "brave-browser", "chrome", "msedge"]
        if os.name == "nt":
            for root in [os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")]:
                if root:
                    candidates += [str(Path(root) / p) for p in ["Google/Chrome/Application/chrome.exe",
                                    "Microsoft/Edge/Application/msedge.exe", "Chromium/Application/chrome.exe"]]
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                       "/Applications/Chromium.app/Contents/MacOS/Chromium",
                       "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        found = []
        for candidate in candidates:
            path = shutil.which(candidate)
            if path and path not in [b["path"] for b in found]:
                found.append({"name": Path(candidate).name, "path": path})
        return found

    def modes(self, state=None, *, client_local=True):
        proxy = state.proxy if state else None
        authenticated = bool(proxy and (urlparse(proxy).username or urlparse(proxy).password))
        graphical = os.name == "nt" or sys.platform == "darwin" or bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
        browser_reason = ("client_remote" if not client_local else "android_webview" if self.platform == "android"
                          else "no_display" if not graphical else "no_browser" if not self.installed_browsers()
                          else "authenticated_proxy" if authenticated else None)
        webview_reason = ("client_remote" if not client_local else "no_webview" if self.webview_opener is None
                          else "webview_proxy" if proxy else None)
        return [{"id": "manual", "available": True, "capturesCookies": False, "reason": None},
                {"id": "browser", "available": browser_reason is None, "capturesCookies": True, "reason": browser_reason},
                {"id": "webview", "available": webview_reason is None, "capturesCookies": True, "reason": webview_reason}]

    def options(self, *, client_local=True):
        sessions = self.transport.diagnostics()
        for session in sessions:
            session["modes"] = self.modes(self.transport.state("https://" + session["domain"]), client_local=client_local)
        return {"browsers": [{"name": b["name"]} for b in self.installed_browsers()] if client_local else [],
                "webviewAvailable": client_local and self.webview_opener is not None,
                "platform": self.platform, "clientLocal": client_local,
                "modes": self.modes(client_local=client_local), "sessions": sessions}

    async def start(self, domain, browser=None, mode="browser"):
        domain = domain.strip().lower()
        state = self.transport.state("https://" + domain)
        if not state.blocked_url:
            raise ValueError("Aucune vérification en attente pour ce domaine")
        url = state.blocked_url
        if not await asyncio.to_thread(is_safe_url, url):
            raise ValueError("URL de vérification non autorisée")
        supported = next((item for item in self.modes(state) if item["id"] == mode and item["available"]), None)
        if not supported or mode == "manual":
            from animelab.api_errors import APIProblem
            raise APIProblem("verification_mode_unavailable", status=409, category="protection", action="open_site")
        async with self._lock:
            await self.expire()
            for job in list(self.jobs.values()):
                if job["domain"] == domain:
                    process = job.get('process')
                    if process and process.poll() is not None:
                        await self.cancel(job['id'])
                        continue
                    return {"id": job["id"], "domain": domain, "mode": job["mode"]}
            if len(self.jobs) >= 3:
                raise ValueError("Fermez une vérification avant d’en ouvrir une autre")
            job = {"id": uuid.uuid4().hex, "domain": domain, "url": url, "created": time.monotonic(),
                   "mode": mode, "process": None, "window": None}
            mechanism = self.mechanisms[mode]
            job["routeProxy"] = state.proxy
            job["routeGeneration"] = state.generation
            await mechanism.open(self, job, state, browser)
            if (job["routeProxy"], job["routeGeneration"]) != (state.proxy, state.generation):
                await mechanism.close(job)
                from animelab.api_errors import APIProblem
                raise APIProblem("verification_route_changed", status=409, category="protection", action="verify")
            self.jobs[job["id"]] = job
            return {"id": job["id"], "domain": domain, "mode": mode}

    async def _cdp(self, job, command, params=None):
        process = job["process"]
        if process.poll() is not None:
            raise ValueError("Le navigateur de vérification a été fermé")
        lines = []
        for _ in range(40):
            try:
                lines = job["port_file"].read_text().splitlines()
                if len(lines) >= 2:
                    break
            except OSError:
                pass
            await asyncio.sleep(0.1)
        if len(lines) < 2:
            raise ValueError("Le navigateur n’a pas encore démarré ; réessayez")
        port = int(lines[0])
        if not 0 < port < 65536 or not lines[1].startswith("/devtools/browser/"):
            raise ValueError("Point de connexion navigateur invalide")
        async with websockets.connect(f"ws://127.0.0.1:{port}{lines[1]}", proxy=None, open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": command, "params": params or {}}))
            async with asyncio.timeout(8):
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("id") == 1:
                        if "error" in message:
                            raise ValueError("Impossible de lire les cookies du navigateur")
                        return message.get("result", {})

    async def complete(self, job_id):
        async with self._lock:
            return await self._complete(job_id)

    async def _complete(self, job_id):
        await self.expire()
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError("Vérification expirée ou introuvable")
        state = self.transport.state(job["url"])
        def check_route():
            if self.jobs.get(job_id) is not job:
                from animelab.api_errors import APIProblem
                raise APIProblem("verification_cancelled", status=409, category="protection", action="verify")
            if "routeProxy" in job and (job["routeProxy"] != state.proxy or job["routeGeneration"] != state.generation):
                from animelab.api_errors import APIProblem
                raise APIProblem("verification_route_changed", status=409, category="protection", action="verify")
        check_route()
        cookies = await self.mechanisms[job["mode"]].cookies(self, job)
        check_route()
        generation = await asyncio.to_thread(self.transport.import_cookies, job["url"], cookies,
                                             expected_route=(state.proxy, state.generation))
        if "routeProxy" in job:
            job["routeGeneration"] = generation
        check_route()
        # Check the upstream response, rather than trusting a user's confirmation.
        media = any(x in urlparse(job["url"]).path.lower() for x in (".mp4", ".m3u8", ".ts", ".m4s"))
        method = "HEAD" if media else "GET"
        try:
            response = await asyncio.to_thread(self.transport.request, method, job["url"],
                                               bypass_cache=True, verify_challenge=True)
            if media and response.status_code in (403, 405, 501):
                async with self.transport.async_client().stream("GET", job["url"], headers={"Range": "bytes=0-1023"}, verify_challenge=True) as upstream:
                    upstream.raise_for_status()
            else:
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"La source refuse encore l’accès (HTTP {exc.response.status_code}) ; la vérification reste en attente") from exc
        except httpx.RequestError as exc:
            raise ValueError("La source est injoignable ; réessayez la validation lorsque la connexion sera rétablie") from exc
        with state.condition:
            check_route()
            state.blocked_url = None
            state.last_error = None
            state.generation += 1
        await self.cancel(job_id)
        return {"success": True, "domain": job["domain"]}

    async def cancel(self, job_id):
        job = self.jobs.pop(job_id, None)
        if job:
            await self.mechanisms[job["mode"]].close(job)

    async def expire(self):
        for job_id, job in list(self.jobs.items()):
            if time.monotonic() - job["created"] > 600:
                await self.cancel(job_id)

    async def watch(self):
        while True:
            await asyncio.sleep(30)
            await self.expire()
            await asyncio.to_thread(self.transport.close_idle)

    async def close(self):
        for job_id in list(self.jobs):
            await self.cancel(job_id)


browser_verification = BrowserVerificationService()
