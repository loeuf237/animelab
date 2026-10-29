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
from animelab.browser_settings import verification_settings, executable
from animelab.services.verification_cookies import snapshot, merge


class BrowserVerificationService:
    def __init__(self, transport=source_http, configuration=None):
        self.transport = transport
        self.configuration = configuration or verification_settings
        self.completed = {}
        self.verified_callback = None
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
        configured = self.configuration.snapshot()['chromiumPath']
        if configured:
            try: candidates = [executable(configured)]
            except ValueError: candidates = []
        found = []
        for candidate in candidates:
            path = shutil.which(candidate)
            if path and path not in [b["path"] for b in found]:
                found.append({"name": Path(candidate).name, "path": path})
        return found

    def remote_headless(self):
        return (os.getenv('ANIMELAB_SHARED_WORKER') == '1' and self.platform == 'desktop'
                and self.configuration.snapshot()['headless'])

    def modes(self, state=None, *, client_local=True):
        proxy = state.proxy if state else None
        authenticated = bool(proxy and (urlparse(proxy).username or urlparse(proxy).password))
        graphical = os.name == "nt" or sys.platform == "darwin" or bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")) or self.configuration.snapshot()["headless"]
        browser_reason = ("client_remote" if not client_local and not self.remote_headless() else "android_webview" if self.platform == "android"
                          else "no_display" if not graphical else "no_browser" if not self.installed_browsers()
                          else "authenticated_proxy" if authenticated else None)
        webview_reason = ("client_remote" if not client_local else "no_webview" if self.webview_opener is None
                          else "webview_proxy" if proxy else None)
        return [{"id": "manual", "available": True, "capturesCookies": False, "reason": None},
                {"id": "browser", "available": browser_reason is None, "capturesCookies": True, "reason": browser_reason,
                 "headless": self.configuration.snapshot()["headless"]},
                {"id": "webview", "available": webview_reason is None, "capturesCookies": True, "reason": webview_reason}]

    def options(self, *, client_local=True):
        sessions = self.transport.diagnostics()
        for session in sessions:
            session["modes"] = self.modes(self.transport.state("https://" + session["domain"]), client_local=client_local)
        return {"browsers": [{"name": b["name"]} for b in self.installed_browsers()] if client_local or self.remote_headless() else [],
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
            if mode=='webview' and any(job['mode']=='webview' for job in self.jobs.values()):
                raise ValueError('Fermez la WebView actuelle avant d’en ouvrir une autre.')
            job = {"id": uuid.uuid4().hex, "domain": domain, "url": url, "created": time.monotonic(),
                   "mode": mode, "process": None, "window": None}
            mechanism = self.mechanisms[mode]
            job["routeProxy"] = state.proxy
            job["routeGeneration"] = state.generation
            initial = snapshot(self.transport, url, visible_only=mode == "webview")
            job['engineCookies'], job['browserCookies'] = initial, initial
            try:
                if mode=='webview':
                    await asyncio.to_thread(self.transport.pause_for_webview,url,job['id'])
                await mechanism.open(self, job, state, browser)
            except BaseException:
                try:
                    await mechanism.close(job)
                finally:
                    self.transport.release_webview(url,job['id'])
                raise
            if (job["routeProxy"], job["routeGeneration"]) != (state.proxy, state.generation):
                try:
                    await mechanism.close(job)
                finally:
                    self.transport.release_webview(url,job['id'])
                from animelab.api_errors import APIProblem
                raise APIProblem("verification_route_changed", status=409, category="protection", action="verify")
            job["needsProbe"] = mode!='webview'
            self.jobs[job["id"]] = job
            return {"id": job["id"], "domain": domain, "mode": mode}

    async def _cdp(self, job, command, params=None):
        process = job["process"]
        if process.poll() is not None:
            raise ValueError("Le navigateur de vérification a été fermé")
        lines = []
        for _ in range(int(job.get("cdpStartTimeout", 4) * 10)):
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

    def status(self, job_id):
        if job_id in self.completed:
            return {'status': 'completed', **self.completed[job_id]['result']}
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError('Vérification expirée ou introuvable')
        return {'status': 'pending', 'id': job_id, 'domain': job['domain'],
                'error': job.get('error', '')}

    async def synchronize(self, job):
        state = self.transport.state(job['url'])
        route = (job.get('routeProxy', state.proxy), job.get('routeGeneration', state.generation))
        mechanism = self.mechanisms[job['mode']]
        current = snapshot(self.transport, job['url'], visible_only=job['mode'] == 'webview')
        remote = await mechanism.cookies(self, job)
        browser, engine, changed = await asyncio.to_thread(merge, self.transport, job['url'], remote,
            job.get('browserCookies', {}), job.get('engineCookies', current), route, job['mode'] == 'webview')
        updates = [value for key, value in engine.items() if browser.get(key) != value]
        updates += [{**value, 'value': '', 'expires': 1} for key, value in browser.items() if key not in engine]
        if updates:
            await mechanism.push(self, job, updates)
        # A route change during CDP/Android I/O invalidates this entire exchange.
        if route != (state.proxy, state.generation):
            from animelab.api_errors import APIProblem
            raise APIProblem('verification_route_changed', status=409, category='protection', action='verify')
        job['browserCookies'], job['engineCookies'] = engine, engine
        if changed: job['needsProbe'] = True
        return changed

    async def complete(self, job_id):
        async with self._lock:
            if job_id in self.completed:
                return self.completed[job_id]['result']
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
        await self.synchronize(job)
        check_route()
        if job['mode']=='webview':
            # Cookie transfer is not an access verdict. Stop browser networking
            # before resuming an actual source operation; never add an HTTP probe.
            await self.mechanisms['webview'].close(job)
            job['windowClosed']=True
            check_route()
        else:
            await self._probe(job)
        with state.condition:
            check_route()
            state.blocked_url = None
            state.last_error = None
            state.generation += 1
            self.transport.release_webview(job['url'],job['id'])
        result = {"success": True, "domain": job["domain"]}
        if job['mode']=='webview':
            result.update(sessionImported=True,accessVerified=False)
        if self.verified_callback:
            result['resumed'] = self.verified_callback(job['domain'])
        self.completed[job_id] = {'created': time.monotonic(), 'result': result}
        await self.cancel(job_id)
        return result

    async def _probe(self, job):
        # Chromium mode retains its existing explicit upstream validation.
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

    async def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job:
            if not job.get('windowClosed'):
                await self.mechanisms[job["mode"]].close(job)
            if self.jobs.get(job_id) is job:
                self.jobs.pop(job_id)
                self.transport.release_webview(job['url'],job['id'])

    async def expire(self):
        for job_id, value in list(self.completed.items()):
            if time.monotonic() - value['created'] > 600:
                self.completed.pop(job_id, None)
        for job_id, job in list(self.jobs.items()):
            if time.monotonic() - job["created"] > 600:
                await self.cancel(job_id)

    async def watch(self):
        while True:
            await asyncio.sleep(1)
            async with self._lock:
                await self.expire()
                for job_id, job in list(self.jobs.items()):
                    try:
                        changed = await self.synchronize(job)
                        if job['mode']=='webview':
                            window=job.get('window')
                            closed=getattr(window,'is_closed',None)
                            if closed is not None and await asyncio.to_thread(closed):
                                await self._complete(job_id)
                            continue  # No emulated upstream probe while a WebView owns the session.
                        if changed or job.pop('needsProbe', False):
                            job['needsProbe'] = False
                            await self._complete(job_id)
                        job['error'] = ''
                    except VerificationRequired:
                        pass  # The page still needs a user's verification.
                    except (ValueError, httpx.HTTPError, OSError) as exc:
                        from animelab.diagnostics import redact_text
                        job['error'] = redact_text(str(exc))
                    except Exception as exc:
                        from animelab.api_errors import APIProblem
                        from animelab.diagnostics import redact_text
                        job['error'] = exc.problem.code if isinstance(exc, APIProblem) else redact_text(str(exc))
                        process = job.get('process')
                        if process and process.poll() is not None:
                            await self.cancel(job_id)
            await asyncio.to_thread(self.transport.close_idle)

    async def close(self):
        for job_id in list(self.jobs):
            await self.cancel(job_id)


browser_verification = BrowserVerificationService()
