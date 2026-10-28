"""Fetch a pinned *evaluation* binary; never installs into production packages."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
LOCK=json.loads((ROOT/'animelab/services/experimental/nm3u8dl-lock.json').read_text())


def prepare(target,directory,archive=None):
    asset=LOCK['assets'][target]
    if archive:
        payload=Path(archive).read_bytes()
    else:
        request=urllib.request.Request(asset['url'],headers={'User-Agent':'AnimeLab-offline-evaluation'})
        with urllib.request.urlopen(request,timeout=60) as response:
            payload=response.read(asset['bytes']+1)
    if len(payload)!=asset['bytes'] or hashlib.sha256(payload).hexdigest()!=asset['sha256']:
        raise ValueError('Upstream archive does not match pinned size/SHA-256')
    executable='N_m3u8DL-RE.exe' if target.startswith('win-') else 'N_m3u8DL-RE'
    if asset['name'].endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            candidates=[info for info in bundle.infolist() if Path(info.filename).name==executable]
            if len(candidates)!=1 or candidates[0].is_dir() or stat.S_ISLNK(candidates[0].external_attr>>16) or candidates[0].file_size>100*1024**2:
                raise ValueError('Unexpected executable in archive')
            content=bundle.read(candidates[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(payload)) as bundle:
            candidates=[info for info in bundle.getmembers() if Path(info.name).name==executable]
            if len(candidates)!=1 or not candidates[0].isfile() or candidates[0].size>100*1024**2:
                raise ValueError('Unexpected executable in archive')
            content=bundle.extractfile(candidates[0]).read()
    digest=hashlib.sha256(content).hexdigest()
    if target=='linux-x64' and digest!=LOCK['linuxX64BinarySha256']:raise ValueError('Unexpected Linux executable hash')
    directory=Path(directory);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    binary=directory/executable
    if binary.exists() and hashlib.sha256(binary.read_bytes()).hexdigest()!=digest:raise FileExistsError('Refuse to overwrite a different executable')
    binary.write_bytes(content);binary.chmod(0o700)
    receipt={'version':LOCK['version'],'target':target,'archiveSha256':asset['sha256'],'binarySha256':digest,
             'compressedBytes':len(payload),'binaryBytes':len(content),'license':LOCK['license'],'source':LOCK['source'],
             'adoption':'evaluation-only; not for production releases'}
    (directory/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',choices=LOCK['assets'],default='linux-x64')
    parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--archive',type=Path,help='Already downloaded upstream archive; SHA-256 is still enforced')
    args=parser.parse_args()
    print(json.dumps(prepare(args.target,args.directory,args.archive),indent=2))


if __name__=='__main__':main()
