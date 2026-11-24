"""Verification mechanisms. A plain client tab never exposes cookies to Python."""
import asyncio
import hashlib
import inspect
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Protocol
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

from animelab.config import settings
from animelab.services.verification_cookies import snapshot


_CLEARANCE_COOKIES = frozenset({'cf_clearance', 'ddg_clearance', '__ddg2_', 'sucuri_cloudproxy'})
_CHALLENGE_TITLES = (
    'just a moment',
    'attention required',
    'checking your browser',
    'ddos-guard',
    'un instant',
    'vérification',
    'cloudflare',
    'please wait',
    'access denied',
    'one more step',
)


def _same_or_subdomain(base_domain: str, candidate_url: str) -> bool:
    base = (base_domain or '').strip().lower()
    host = (urlparse(candidate_url or '').hostname or '').lower()
    if not base or not host:
        return False
    apex = '.'.join(base.split('.')[-2:])
    return host == base or host == apex or host.endswith('.' + apex)


def _is_challenge_title(title: str) -> bool:
    low = (title or '').strip().lower()
    return not low or any(marker in low for marker in _CHALLENGE_TITLES)


class VerificationMechanism(Protocol):
    async def open(self, service, job: dict, state, browser: str | None) -> None: ...
    async def cookies(self, service, job: dict) -> list[dict]: ...
    async def close(self, job: dict) -> None: ...


class ChromiumVerification:
    async def open(self, service, job, state, browser=None):
        domain, url = job['domain'], job['url']
        installed = service.installed_browsers()
        selected = next((b for b in installed if b["name"] == browser), None) if browser else next(iter(installed), None)
        if not selected:
            raise ValueError("Aucun Chrome, Chromium, Edge ou Brave installé n’a été trouvé")
        headless = service.configuration.snapshot()['headless']
        if not headless and os.name != "nt" and not os.getenv("DISPLAY") and not os.getenv("WAYLAND_DISPLAY") and sys.platform != 'darwin':
            raise ValueError("Cette machine ne dispose pas d’une session graphique")
        profile = settings.CACHE_DIR / "verification_profiles" / hashlib.sha256((domain + str(state.proxy)).encode()).hexdigest()
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(profile, 0o700)
        port_file = profile / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        args = [selected["path"], f"--user-data-dir={profile}", "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
                "--disable-background-mode"]
        if headless:
            args.extend(["--headless=new", "--new-window", "about:blank"])
        else:
            args.extend(["--app=about:blank", "--window-size=920,740", "--disable-extensions", "--disable-sync"])
        if state.proxy:
            parsed = urlparse(state.proxy)
            if parsed.username or parsed.password:
                raise ValueError("La vérification intégrée nécessite un proxy sans authentification")
            args.insert(-1, "--proxy-server=" + state.proxy)
        job["process"] = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        job["headless"] = bool(headless)
        job["port_file"] = port_file
        job['cdpStartTimeout'] = 30
        identity = await service._cdp(job, 'Browser.getVersion')
        service.transport.adopt_browser_identity(url, identity['userAgent'],
            (job['routeProxy'], job['routeGeneration']))
        await service._cdp(job, 'Storage.clearCookies')
        initial = snapshot(service.transport, url)
        job['initialCookieKeys'] = set(initial.keys())
        await self.push(service, job, list(initial.values()))
        targets = (await service._cdp(job, 'Target.getTargets')).get('targetInfos', [])
        page_target = next((t for t in targets if t.get('type') == 'page' and t.get('targetId')), None)
        navigated = False
        if page_target and hasattr(service, '_cdp_navigate'):
            navigated = await service._cdp_navigate(job, page_target['targetId'], url)
        if not navigated:
            await service._cdp(job, 'Target.createTarget', {'url': url})
            for target in targets:
                if target.get('url') == 'about:blank' and target.get('targetId'):
                    await service._cdp(job, 'Target.closeTarget', {'targetId': target['targetId']})
        job['cdpStartTimeout'] = 4

    @staticmethod
    async def ready_to_auto_close(service, job) -> bool:
        if not job.get('autoClose') or job.get('headless'):
            return False
        process = job.get('process')
        if not process or process.poll() is not None or not job.get('port_file'):
            return False
        if time.monotonic() - float(job.get('created') or 0.0) < 2.0:
            return False
        try:
            targets = (await service._cdp(job, 'Target.getTargets')).get('targetInfos', [])
        except Exception:
            job['clearTicks'] = 0
            return False
        page_targets = [t for t in targets if t.get('type') == 'page' and _same_or_subdomain(job['domain'], t.get('url', ''))]
        if any(_is_challenge_title(t.get('title', '')) for t in page_targets):
            job['sawChallenge'] = True
            job['clearTicks'] = 0
            return False
        clean_page = any(not _is_challenge_title(t.get('title', '')) for t in page_targets)
        if not clean_page:
            job['clearTicks'] = 0
            return False
        cookies = list(job.get('capturedCookies') or [])
        has_clearance = any(c.get('name') in _CLEARANCE_COOKIES for c in cookies)
        if not has_clearance and not job.get('sawChallenge'):
            job['clearTicks'] = 0
            return False
        job['clearTicks'] = int(job.get('clearTicks') or 0) + 1
        return job['clearTicks'] >= 2

    async def cookies(self, service, job):
        if job.get('process') and job['process'].poll() is not None:
            if 'capturedCookies' not in job:
                raise ValueError('Le navigateur a fermé avant le transfert de session ; rouvrez la vérification.')
            return job['capturedCookies']
        job['capturedCookies'] = (await service._cdp(job, "Storage.getCookies")).get("cookies", [])
        return job['capturedCookies']

    async def push(self, service, job, cookies):
        values = []
        for item in cookies:
            value = {key: item[key] for key in ('name', 'value', 'domain', 'path', 'secure', 'httpOnly') if key in item}
            if not item.get('domain', '').startswith('.'):
                value.pop('domain', None)
                scheme = 'https' if item.get('secure') else urlparse(job['url']).scheme
                value['url'] = scheme + '://' + item['domain'] + item.get('path', '/')
            if item.get('sameSite'): value['sameSite'] = item['sameSite']
            if item.get('expires'): value['expires'] = item['expires']
            values.append(value)
        if values:
            await service._cdp(job, 'Storage.setCookies', {'cookies': values})

    async def close(self, job):
        process = job.get('process')
        if process and process.poll() is None:
            process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await asyncio.to_thread(process.wait)


class WebViewVerification:
    @staticmethod
    def desktop_closed(job):
        win = job.get('window')
        event = getattr(getattr(win, 'events', None), 'closed', None)
        if event is not None and event.is_set():
            return True
        is_closed = getattr(win, 'is_closed', None)
        return bool(callable(is_closed) and is_closed())

    @staticmethod
    def _accepts_auto_close(opener) -> bool:
        try:
            sig = inspect.signature(opener)
        except (TypeError, ValueError):
            return False
        for param in sig.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD or param.name == 'auto_close':
                return True
        return False

    async def open(self, service, job, state, browser=None):
        identity = getattr(service.webview_opener, 'user_agent', None)
        if identity:
            service.transport.adopt_browser_identity(job['url'], await asyncio.to_thread(identity),
                (job['routeProxy'], job['routeGeneration']))
        # Seed before navigation so the initial document receives the HTTP session.
        seed = getattr(service.webview_opener, 'seed_cookies', None)
        if seed:
            await asyncio.to_thread(seed, job['url'], list(snapshot(service.transport, job['url'], visible_only=True).values()))
        opener = service.webview_opener
        if self._accepts_auto_close(opener):
            job['window'] = await asyncio.to_thread(lambda: opener(job['url'], auto_close=job.get('autoClose', True)))
        else:
            job['window'] = await asyncio.to_thread(opener, job['url'])

    async def cookies(self, service, job):
        if self.desktop_closed(job):
            if 'capturedCookies' not in job:
                records = getattr(job.get('window'), 'get_cookie_records', None)
                if records:
                    final_records = await asyncio.to_thread(records)
                    if final_records:
                        job['capturedCookies'] = final_records
                        return final_records
                raise ValueError('La fenêtre a fermé avant le transfert de session ; rouvrez la vérification.')
            return job['capturedCookies']
        records = getattr(job['window'], 'get_cookie_records', None)
        if records:
            result = await asyncio.to_thread(records)
            job['capturedCookies'] = result
            return result
        cookies = []
        for jar in await asyncio.to_thread(job['window'].get_cookies):
            for name, morsel in jar.items():
                expiry = morsel['expires']
                cookies.append({'name': name, 'value': morsel.value,
                    'domain': morsel['domain'] or job['domain'], 'path': morsel['path'] or '/',
                    'secure': bool(morsel['secure']),
                    'expires': parsedate_to_datetime(expiry).timestamp() if expiry else None})
        job['capturedCookies'] = cookies
        return cookies

    async def push(self, service, job, cookies):
        if self.desktop_closed(job):
            return
        setter = getattr(job['window'], 'set_cookies', None)
        if setter:
            await asyncio.to_thread(setter, cookies)

    async def close(self, job):
        if job.get('window') and not self.desktop_closed(job):
            await asyncio.to_thread(job['window'].destroy)
