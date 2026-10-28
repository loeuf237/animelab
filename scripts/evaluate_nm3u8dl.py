"""Offline P10-P12 evaluation; requires the pinned Linux x64 binary and unshare.

All upstream bytes are synthetic and served by a mock transport. N_m3u8DL-RE
itself runs against a private HTTP relay in a new network namespace. This command
never installs the tool and never enables a production backend.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class FixtureOrigin:
    def __init__(self,root):self.root=Path(root).resolve();self.calls=[];self.offline=False;self.truncated=None;self.cancel=None;self.redirect=None
    def validate(self,url):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='fixture.example':raise ValueError('Synthetic origin only')
    def handler(self,request):
        import httpx
        self.validate(str(request.url));self.calls.append(request)
        if self.offline:raise httpx.ConnectError('Synthetic interruption',request=request)
        if self.redirect:return httpx.Response(302,headers={'location':self.redirect})
        path=(self.root/urlsplit(str(request.url)).path.lstrip('/')).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():return httpx.Response(404)
        content=path.read_bytes();etag='"'+hashlib.sha256(content).hexdigest()+'"'
        if request.headers.get('if-none-match')==etag:return httpx.Response(304,headers={'etag':etag})
        headers={'etag':etag,'content-type':'application/octet-stream'};code=200
        if request.headers.get('range'):
            start,end=map(int,request.headers['range'].removeprefix('bytes=').split('-'));length=len(content)
            content=content[start:end+1];headers['content-range']=f'bytes {start}-{end}/{length}';code=206
        headers['content-length']=str(len(content))
        if self.truncated and path.name==self.truncated:content=content[:-7]
        if self.cancel and path.suffix=='.ts':self.cancel()
        return httpx.Response(code,headers=headers,content=content)
    def client(self,**kwargs):
        import httpx
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler),**kwargs)


def probe(path):
    return json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True).stdout)


def video_hash(path):
    data=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(path),'-map','0:v:0','-f','framemd5','-'],capture_output=True,check=True).stdout
    frames=b'\n'.join(line.split(b',')[-1].strip() for line in data.splitlines() if line and not line.startswith(b'#'))
    return hashlib.sha256(frames).hexdigest()


async def evaluate(tool,work):
    from types import SimpleNamespace
    from scripts.nm3u8dl_fixtures import generate
    from animelab.services.experimental.nm3u8dl_backend import N_m3u8Backend,LOCK
    from animelab.services.experimental.manifest_relay import ManifestRelay
    from animelab.services.media_contracts import ResolvedMedia,validate_hls_capabilities,UnsupportedMedia
    paths=generate(work/'fixtures');origin=FixtureOrigin(work/'fixtures');rows=[]
    reference=video_hash(work/'fixtures/reference.mp4')
    for name,path in paths.items():
        task=SimpleNamespace(id=name,cancelled=False,paused=False)
        media=ResolvedMedia('https://fixture.example/'+str(path.relative_to(work/'fixtures')),protocol='dash' if name=='dash' else 'hls')
        backend=N_m3u8Backend(work/'jobs',tool,evaluation=True,client_factory=origin.client,validator=origin.validate,clock_probe=name=='discontinuity')
        before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic();events=[]
        try:
            result=await backend.transfer(task,media,events.append)
            after=resource.getrusage(resource.RUSAGE_CHILDREN)
            inventory=probe(result.path)
            native=True
            try:
                if name=='dash':raise UnsupportedMedia('No native DASH backend')
                validate_hls_capabilities(path.read_text())
            except UnsupportedMedia:native=False
            elapsed=time.monotonic()-start
            row={'case':name,'success':result.complete,'assembled':True,'nativeCapability':native,'durationSeconds':float(inventory['format']['duration']),
                 'negativeClockProbe':name=='discontinuity',
                 'elapsedSeconds':round(elapsed,3),'cpuSeconds':round(after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,3),
                 'syntheticPipelineKiBPerSecond':round(backend.last_relay.downloaded/1024/elapsed,2),
                 'peakChildRssKiB':after.ru_maxrss,'workspaceBytes':sum(f.stat().st_size for f in Path(result.checkpoint['workspace']).rglob('*') if f.is_file()),
                 'upstreamBytes':backend.last_relay.downloaded,'upstreamRequests':backend.last_relay.requests,
                 'networkObservation':backend.last_network,
                 'streamTypes':[s['codec_type'] for s in inventory['streams']], 'videoFramesMatchReference':video_hash(result.path)==reference}
            if name in ('subtitle','discontinuity'):
                subs=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',result.path,'-map','0:s:0','-f','srt','-'],capture_output=True,check=True).stdout.decode('utf-8-sig')
                from animelab.services.subtitle_timing import intervals
                row['subtitleTimes']=intervals(subs.encode(),'.srt')
                row['subtitleClockCorrect']=all(abs(a-b)<.04 for pair,expected in zip(row['subtitleTimes'],[(.2,.8),(2.2,2.8)]) for a,b in zip(pair,expected)) and len(row['subtitleTimes'])==2
            rows.append(row)
        except Exception as exc:rows.append({'case':name,'success':False,'reason':type(exc).__name__+': '+str(exc)})
    # Same sealed VOD, tool's own cache deliberately damaged. This is an offline
    # experiment to test the upstream resume guarantee, not a safe resume path.
    task=SimpleNamespace(id='simple',cancelled=False,paused=False)
    backend=N_m3u8Backend(work/'jobs',tool,evaluation=True,client_factory=origin.client,validator=origin.validate)
    directory=work/'jobs'/hashlib.sha256(task.id.encode()).hexdigest()[:24]
    first=next((directory/'tool-cache').rglob('0.ts'))
    original=first.read_bytes();first.write_bytes(b'bad fragment')
    requests_before=len(origin.calls)
    start=time.monotonic()
    try:
        unsafe=await backend.transfer(task,ResolvedMedia('https://fixture.example/simple/index.m3u8',protocol='hls'),lambda event:None,unsafe_cache_probe=True)
        corruption={'accepted':True,'durationSeconds':probe(unsafe.path)['format']['duration'],'framesMatchReference':video_hash(unsafe.path)==reference}
    except Exception as exc:corruption={'accepted':False,'reason':type(exc).__name__+': '+str(exc)}
    corruption['upstreamReportedSuccess']='"returncode": 0' in backend.last_console
    corruption['upstreamFragmentsFetched']=sum(req.url.path.endswith('.ts') and 'if-none-match'not in req.headers for req in origin.calls[requests_before:])
    # Prove that the independently checked relay cache can regenerate it safely.
    recovered=await backend.transfer(task,ResolvedMedia('https://fixture.example/simple/index.m3u8',protocol='hls'),lambda event:None)
    corruption['safeRebuildFramesMatchReference']=video_hash(recovered.path)==reference
    corruption['cacheProbeElapsedSeconds']=round(time.monotonic()-start,3)
    assert original
    return {'schemaVersion':1,'tool':LOCK['version'],'archiveSha256':LOCK['assets']['linux-x64']['sha256'],
            'binarySha256':LOCK['linuxX64BinarySha256'],'platform':sys.platform,'synthetic':True,'network':'mock SourceHTTP-compatible acquisition; external tool in private network namespace',
            'headlessWorkaround':'--force-ansi-console; COLUMNS=160; LINES=50','cases':rows,'corruptToolCache':corruption,
            'metricsLimit':'4 second synthetic samples; peak RSS is cumulative child high-water mark, not per-case allocation; no Internet throughput claim',
            'productionBackendEnabled':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tool',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='animelab-nm3u8dl-étude ') as temp:
        report=asyncio.run(evaluate(args.tool,Path(temp)))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
