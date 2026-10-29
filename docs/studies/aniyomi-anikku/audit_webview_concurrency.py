"""Offline control-flow audit (not a physical-device acceptance test).

The upstream request and WebView are fakes. No production site or browser opens.
Run from the repository root with uv run --locked python <this file>.
"""
import asyncio
from contextlib import suppress
import json
from pathlib import Path
import sys
import tempfile
import subprocess
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))


async def audit(directory):
    import httpx
    from animelab.services.browser_verification import BrowserVerificationService
    from animelab.services.source_http import SourceHTTPService
    from animelab.services.proxy_service import proxy_service

    class Window:
        open=True
        def get_cookie_records(self):
            return []
        def destroy(self):
            self.open=False
    window=Window()
    calls=[]
    observed=asyncio.Event()
    loop=asyncio.get_running_loop()
    def request(method,url,**kwargs):
        calls.append({'method':method,'webviewOpen':window.open,'verifyChallenge':kwargs.get('verify_challenge',False)})
        loop.call_soon_threadsafe(observed.set)
        return httpx.Response(200,request=httpx.Request(method,url))
    transport=SourceHTTPService(storage=directory/'cookies')
    service=BrowserVerificationService(transport)
    service.platform='android'
    service.webview_opener=lambda url:window
    with patch.object(proxy_service,'get_random_proxy',return_value=None), \
         patch('animelab.services.browser_verification.is_safe_url',return_value=True), \
         patch.object(transport,'request',side_effect=request):
        state=transport.state('https://fixture.invalid/catalogue')
        state.blocked_url='https://fixture.invalid/catalogue'
        await service.start('fixture.invalid',mode='webview')
        watcher=asyncio.create_task(service.watch())
        try:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(observed.wait(),2.2)
            commit=subprocess.run(['git','rev-parse','--short','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
            dirty=subprocess.run(['git','diff','--quiet'],cwd=ROOT).returncode!=0
            return {'sourceCommit':commit,'worktreeModified':dirty,'testKind':'offline_control_flow_with_fake_webview_and_upstream',
                    'realExternalRequests':0,'realBrowserOpened':False,'browserCookiesChanged':False,
                    'simulatedUpstreamCalls':calls,
                    'concurrentProbeReproduced':any(call['webviewOpen'] for call in calls)}
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            await service.close()
            transport.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='animelab-webview-audit-') as temporary:
        print(json.dumps(asyncio.run(audit(Path(temporary))),indent=2))
