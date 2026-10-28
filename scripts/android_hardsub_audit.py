"""Audit the JNI probe's ABI, native 16 KB alignment and packaged size on CI."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZipFile


def audit(apk, abi):
    machines = {'arm64-v8a': 183, 'x86_64': 62}
    libraries = []
    with ZipFile(apk) as archive:
        for name in archive.namelist():
            if not name.startswith('lib/') or not name.endswith('.so'):
                continue
            data = archive.read(name)
            if name.split('/')[1] != abi or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != machines[abi]:
                raise ValueError('Unexpected JNI ABI: ' + name)
            phoff = struct.unpack_from('<Q', data, 32)[0]
            entsize, count = struct.unpack_from('<HH', data, 54)
            loads = 0
            for i in range(count):
                kind, _, offset, address, _, _, _, align = struct.unpack_from('<IIQQQQQQ', data, phoff + i * entsize)
                if kind == 1:
                    loads += 1
                    if align < 16384 or align & (align - 1) or offset % 16384 != address % 16384:
                        raise ValueError('Native library is not 16 KB aligned: ' + name)
            if not loads:
                raise ValueError('Missing ELF load segments: ' + name)
            libraries.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    if not libraries or not any('libavfilter' in row['path'] for row in libraries):
        raise ValueError('Missing native FFmpeg filter libraries')
    return dict(abi=abi, apkBytes=apk.stat().st_size, nativeBytes=sum(row['bytes'] for row in libraries),
                elf16kbAligned=True, device16kbTested=False, libraries=libraries)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--abi', choices=['arm64-v8a', 'x86_64'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.apk, args.abi), indent=2) + '\n')
