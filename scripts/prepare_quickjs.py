"""Fetch exact QuickJS 0.9.2 sources; native compilation happens in Android CI.

The original Java/JNI ABI is retained. Git blob identities and exact sizes come
from the pinned upstream tree; this never repackages the legacy 4 KiB ELF file.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'android/quickjs-compat/upstream.json'
MAX_TOTAL=4_000_000


def git_blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def verified_bytes(data,record):
    if len(data)!=record['size'] or git_blob(data)!=record['git_blob']:
        raise ValueError('QuickJS source identity mismatch: '+record['path'])
    return data


def prepare(output,manifest=None,fetch=None):
    info=manifest or json.loads(MANIFEST.read_text())
    files=info['files']
    if sum(item['size'] for item in files)>MAX_TOTAL:
        raise ValueError('QuickJS source budget exceeded')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    def one(record):
        relative=Path(record['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('LICENSE','quickjs'):
            raise ValueError('Unexpected upstream source path')
        target=output/relative
        if target.exists():
            try:
                return record,verified_bytes(target.read_bytes(),record)
            except ValueError:
                pass
        url='https://raw.githubusercontent.com/cashapp/zipline/'+info['commit']+'/'+record['path']
        if fetch:
            data=fetch(url,record['size'])
        else:
            chunks=[]
            count=0
            started=time.monotonic()
            with urlopen(url,timeout=45) as response:
                while chunk:=response.read(65536):
                    count+=len(chunk)
                    if count>record['size']:
                        raise ValueError('Unexpected upstream source size')
                    chunks.append(chunk)
                    # Bound even the largest source fetch; no APK is downloaded.
                    time.sleep(max(0,count/262144-(time.monotonic()-started)))
            data=b''.join(chunks)
        verified_bytes(data,record)
        target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as temporary:
            temporary.write(data)
        os.replace(temporary.name,target)
        return record,data
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources=list(pool.map(one,files))
    contents={record['path']:data for record,data in sources}
    licenses=output/'licenses'
    licenses.mkdir(exist_ok=True)
    (licenses/'QuickJS-wrapper-APACHE-2.0.txt').write_bytes(contents['LICENSE'])
    engine=contents['quickjs/common/native/quickjs/quickjs.c'].split(b'*/',1)[0]+b'*/\n'
    (licenses/'QuickJS-engine-MIT.txt').write_bytes(engine)
    receipt={**info,'requested_native_alignment':16384,'sources_modified':False,
             'files':[{**record,'sha256':hashlib.sha256(data).hexdigest()} for record,data in sources]}
    (licenses/'QuickJS-source-info.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    info=prepare(args.output)
    print(json.dumps({'quickjs':info['version'],'commit':info['commit'],'verified_sources':len(info['files'])}))
