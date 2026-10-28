"""Inspect the packaged Android engine and generate traceable release metadata."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile


def inspect_apk(path, require_optimized=False):
    names, native = [], []
    def inspect_zip(data, prefix="", depth=0):
        if depth > 3:
            raise ValueError("Unexpected nested Android archives")
        with zipfile.ZipFile(data) as archive:
            for item in archive.infolist():
                name = prefix + item.filename
                names.append(name)
                if item.filename.endswith((".so", ".imy", ".zip")):
                    content = archive.read(item)
                    if content.startswith(b"\x7fELF"):
                        if require_optimized and "requirements-" in name:
                            try:
                                from scripts.android_apk_size import elf_sections
                            except ModuleNotFoundError:
                                from android_apk_size import elf_sections
                            if any(n.startswith((".debug", ".zdebug")) or n == ".symtab"
                                   for n in elf_sections(content)):
                                raise ValueError("Unstripped Python native library: " + name)
                        if content[4:6] != b"\x02\x01" or struct.unpack_from("<H", content, 18)[0] != 183:
                            raise ValueError("Non-ARM64 native library: " + name)
                        ph_offset = struct.unpack_from("<Q", content, 32)[0]
                        ph_size, ph_count = struct.unpack_from("<HH", content, 54)
                        segments = []
                        for index in range(ph_count):
                            offset = ph_offset + index * ph_size
                            kind = struct.unpack_from("<I", content, offset)[0]
                            address = struct.unpack_from("<Q", content, offset + 16)[0]
                            size = struct.unpack_from("<Q", content, offset + 40)[0]
                            alignment = struct.unpack_from("<Q", content, offset + 48)[0]
                            segments.append((kind, address, size, alignment))
                            if kind == 1:
                                if alignment < 16384:
                                    raise ValueError("Native library is not 16 KB aligned: " + name)
                        # p_align alone misses NDK r26 libraries whose RELRO
                        # protection extends into an unmapped page at load time.
                        loads = [(a, s) for k, a, s, _ in segments if k == 1]
                        for kind, address, size, _ in segments:
                            if kind == 0x6474E552 and size:
                                # Bionic uses the device page size, not p_align.
                                # A small valid LOAD may end mid-page; its mapped
                                # extent is rounded up too. Check 4 KB and 16 KB
                                # devices, including gaps between LOAD segments.
                                for page in (4096, 16384):
                                    cursor = address // page * page
                                    end = (address + size + page - 1) // page * page
                                    for low, high in sorted((a // page * page, (a + s + page - 1) // page * page) for a, s in loads):
                                        if low > cursor: break
                                        cursor = max(cursor, high)
                                        if cursor >= end: break
                                    if cursor < end:
                                        raise ValueError(f"Native RELRO exceeds mapped {page // 1024} KB pages: " + name)
                        native.append(name)
                    elif content.startswith(b"PK"):
                        inspect_zip(io.BytesIO(content), name + "/", depth + 1)
    inspect_zip(path)
    for marker in ("frontend/dist/index.html", "android_runtime.py", "animelab/services/download_manager", "curl_cffi/_wrapper", "pydantic_core/_pydantic_core", "libffmpegkit"):
        if not any(marker in name for name in names):
            raise ValueError("Missing packaged engine component: " + marker)
    if not native:
        raise ValueError("No native engine libraries found")
    with zipfile.ZipFile(path) as apk:
        build_manifest = "assets/chaquopy/build.json"
        if build_manifest in apk.namelist():
            assets = json.loads(apk.read(build_manifest))["assets"]
            for name, expected in assets.items():
                if hashlib.sha1(apk.read("assets/chaquopy/" + name)).hexdigest() != expected:
                    raise ValueError("Chaquopy asset hash mismatch: " + name)
        elif require_optimized:
            raise ValueError("Missing Chaquopy build manifest")
        if require_optimized:
            dex = b"".join(apk.read(n) for n in apk.namelist() if n.endswith(".dex"))
            for bridge in ("MediaBridge", "CryptoBridge", "NativeHooks", "VerificationBridge", "StorageAccess"):
                if ("Lcom/animan/app/" + bridge + ";").encode() not in dex:
                    raise ValueError("Missing Python/JNI bridge after R8: " + bridge)
            if any("/lxml/" in name or "libxml2" in name or "libxslt" in name for name in names):
                raise ValueError("Unused native XML dependency is still packaged")
    return {"embedded_spa": True, "embedded_python_engine": True, "abi": "arm64-v8a",
            "native_16kb_alignment": True, "native_libraries": native,
            "a11_optimized_packaging_checked": require_optimized}


def manifest(apk, output, validation=False, optimized=False):
    report = inspect_apk(apk, require_optimized=optimized)
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    configuration = (root / "android/app/build.gradle.kts").read_text()
    version = re.search(r'versionName\s*=\s*"([^"]+)"', configuration).group(1)
    version_code = int(re.search(r'versionCode\s*=\s*(\d+)', configuration).group(1))
    report.update({"version": version, "version_code": version_code, "min_android_api": 29,
                   "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                   "physical_device_tested": False, "validation_key_only": validation,
                   "ffmpeg": "dev.ffmpegkit-maintained:ffmpeg-kit-full-gpl:6.0.4",
                   "python": "3.13", "curl_cffi": "0.16.3"})
    (output / "Android-build-info.json").write_text(json.dumps(report, indent=2))
    (output / "SHA256SUMS.txt").write_text(hashlib.file_digest(apk.open("rb"), "sha256").hexdigest() + "  " + apk.name + "\n")
    if not validation and not os.getenv("ANIMAN_ANDROID_KEYSTORE"):
        raise RuntimeError("Publication requires the dedicated Android release signing identity")
    print(json.dumps({key: value for key, value in report.items() if key != "native_libraries"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("--optimized", action="store_true")
    args = parser.parse_args()
    manifest(args.apk, args.output, args.validation, args.optimized)
