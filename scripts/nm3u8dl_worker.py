"""Internal offline evaluation worker, invoked only in a fresh network namespace.

No app imports, provider URLs, credentials or remote fetches. Serve a sealed set
of generated local files on namespace-private loopback, including strict Range.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import resource
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


def main():
    directory,tool,ffmpeg=map(lambda value:Path(value).resolve(),sys.argv[1:4])
    parent_namespace=sys.argv[4]
    if os.readlink('/proc/self/ns/net')==parent_namespace:
        raise RuntimeError('Offline worker requires a different network namespace')
    subprocess.run(['/usr/sbin/ip','link','set','lo','up'],check=True,capture_output=True)
    # Prove that there is no external route before any tool invocation.
    with socket.socket() as probe:
        probe.settimeout(.1)
        if probe.connect_ex(('192.0.2.1',443))!=101:
            raise RuntimeError('Unexpected external route in the worker namespace')
    plan=json.loads((directory/'plan.json').read_text())
    if plan.get('version')!=1 or plan['entry'] not in plan['files']:raise ValueError('Invalid sealed plan')
    for name,expected in plan['files'].items():
        if not re.fullmatch(r'[0-9a-f]{64}(?:_\d+)?\.[a-z0-9]+',name):raise ValueError('Invalid resource identity')
        path=directory/name
        if path.is_symlink() or path.resolve().parent!=directory or path.stat().st_size!=expected['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=expected['sha256']:
            raise ValueError('Resource integrity check failed')
    capability=secrets.token_urlsafe(32)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.send_file(False)
        def do_HEAD(self):self.send_file(True)
        def send_file(self,head):
            parts=urlsplit(self.path)
            prefix='/'+capability+'/'
            name=parts.path[len(prefix):] if parts.path.startswith(prefix) else ''
            if name not in plan['files'] or parts.query or parts.fragment:
                self.send_error(404);return
            # Fault injection for the offline cancellation corpus only.
            delay=float(os.getenv('ANIMELAB_NM3U8DL_EVAL_DELAY','0'))
            if 0<delay<=2:time.sleep(delay)
            size=plan['files'][name]['size'];start,end=0,size-1
            bounds=self.headers.get('Range')
            if bounds:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',bounds)
                if not match:self.send_error(416);return
                start=int(match[1]);end=min(end,int(match[2])) if match[2] else end
                if not 0<=start<=end<size:self.send_error(416);return
            self.send_response(206 if bounds else 200)
            self.send_header('Content-Length',str(end-start+1))
            self.send_header('Content-Type','application/vnd.apple.mpegurl' if name.endswith('.m3u8') else 'application/dash+xml' if name.endswith('.mpd') else 'application/octet-stream')
            if bounds:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not head:
                with (directory/name).open('rb') as source:
                    source.seek(start);remaining=end-start+1
                    while remaining:
                        block=source.read(min(65536,remaining))
                        if not block:break
                        self.wfile.write(block);remaining-=len(block)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    work=directory.parent
    output=work/'assembled';temporary=work/'tool-cache'
    output.mkdir(exist_ok=True);temporary.mkdir(exist_ok=True)
    args=[str(tool),f'http://127.0.0.1:{server.server_port}/{capability}/{plan["entry"]}',
        '--save-dir',str(output),'--tmp-dir',str(temporary),'--save-name','assembled',
        '--auto-select','--force-ansi-console','--disable-update-check','--no-log','--no-ansi-color',
        '--write-meta-json','false','--use-system-proxy','false','--download-retry-count','0',
        '--del-after-done','false','--ffmpeg-binary-path',str(ffmpeg),'--use-ffmpeg-concat-demuxer',
        '--mux-after-done','format=mkv:muxer=ffmpeg:keep=true']
    env={key:os.environ[key] for key in ('PATH','LANG','LC_ALL') if key in os.environ}
    env.update(HOME=str(work),XDG_CONFIG_HOME=str(work/'config'),DOTNET_EnableDiagnostics='0',COLUMNS='160',LINES='50',TERM='xterm')
    try:
        trace=work/'network.trace'
        tracer=shutil.which('strace')
        if tracer:args=[tracer,'-f','-qq','-e','trace=connect','-o',str(trace),*args]
        before=resource.getrusage(resource.RUSAGE_CHILDREN)
        result=subprocess.run(args,env=env,check=False)
        usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        raw=trace.read_text() if tracer and trace.is_file() else ''
        addresses=sorted(set(re.findall(r'inet_addr\("([0-9.]+)"\)',raw)))
        ipv6=sorted(set(re.findall(r'inet_pton\(AF_INET6, "([^"]+)"',raw)))
        if any(address!='127.0.0.1' for address in addresses) or any(address not in ('::1','::ffff:127.0.0.1') for address in ipv6):raise RuntimeError('Unexpected external connection attempt')
        print('\nANIMELAB_OFFLINE_RESULT='+json.dumps({'returncode':result.returncode,'networkIsolated':True,'connectTraceAvailable':bool(tracer),'observedIPv4':addresses,'observedIPv6':ipv6,
             'peakWorkerChildRssKiB':usage.ru_maxrss,'workerChildCpuSeconds':round(usage.ru_utime+usage.ru_stime-before.ru_utime-before.ru_stime,4)}),flush=True)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
    sys.exit(0 if result.returncode==0 else 1)


if __name__=='__main__':main()
