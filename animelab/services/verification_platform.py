"""Verification mechanisms. A plain client tab never exposes cookies to Python."""
import asyncio
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

from animelab.config import settings
from animelab.services.source_http import USER_AGENT
from animelab.services.verification_cookies import snapshot


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
                "--disable-background-mode", f"--user-agent={USER_AGENT}", "--new-window", "about:blank"]
        if headless: args.insert(1, "--headless=new")
        if state.proxy:
            parsed = urlparse(state.proxy)
            if parsed.username or parsed.password:
                raise ValueError("La vérification intégrée nécessite un proxy sans authentification")
            args.insert(-2, "--proxy-server=" + state.proxy)
        job["process"] = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        job["port_file"] = port_file
        job['cdpStartTimeout'] = 30
        await service._cdp(job, 'Storage.clearCookies')
        initial = snapshot(service.transport, url)
        await self.push(service, job, list(initial.values()))
        await service._cdp(job, 'Target.createTarget', {'url': url})
        for target in (await service._cdp(job, 'Target.getTargets')).get('targetInfos', []):
            if target.get('url') == 'about:blank':
                await service._cdp(job, 'Target.closeTarget', {'targetId': target['targetId']})
        job['cdpStartTimeout'] = 4

    async def cookies(self, service, job):
        return (await service._cdp(job, "Storage.getCookies")).get("cookies", [])

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
    async def open(self, service, job, state, browser=None):
        # Seed before navigation so the initial document receives the HTTP session.
        seed = getattr(service.webview_opener, 'seed_cookies', None)
        if seed:
            await asyncio.to_thread(seed, job['url'], list(snapshot(service.transport, job['url'], visible_only=True).values()))
        job['window'] = await asyncio.to_thread(service.webview_opener, job['url'])

    async def cookies(self, service, job):
        records = getattr(job['window'], 'get_cookie_records', None)
        if records:
            return await asyncio.to_thread(records)
        cookies = []
        for jar in await asyncio.to_thread(job['window'].get_cookies):
            for name, morsel in jar.items():
                expiry = morsel['expires']
                cookies.append({'name': name, 'value': morsel.value,
                    'domain': morsel['domain'] or job['domain'], 'path': morsel['path'] or '/',
                    'secure': bool(morsel['secure']),
                    'expires': parsedate_to_datetime(expiry).timestamp() if expiry else None})
        return cookies

    async def push(self, service, job, cookies):
        setter = getattr(job['window'], 'set_cookies', None)
        if setter:
            await asyncio.to_thread(setter, cookies)

    async def close(self, job):
        if job.get('window'):
            await asyncio.to_thread(job['window'].destroy)
