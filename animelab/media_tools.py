"""Small platform boundary for FFmpeg/FFprobe and AES-CBC.

Android executes FFmpeg through JNI, never an executable extracted into writable
app storage. Desktop retains subprocesses and cryptography.
"""
import json
from pathlib import Path
import shutil
import subprocess

_native_media = None
_native_aes = None


def configure_android(media, aes):
    global _native_media, _native_aes
    _native_media, _native_aes = media, aes


def is_native():
    return _native_media is not None


def which(name):
    if name not in ("ffmpeg", "ffprobe"):
        raise ValueError("Unsupported media tool")
    return name if is_native() else shutil.which(name)


def run(args, *, capture_output=True, text=True, timeout=30, check=False, cwd=None):
    if not is_native():
        kwargs = dict(capture_output=capture_output, text=text, timeout=timeout, check=check)
        if cwd is not None:
            kwargs["cwd"] = cwd
        return subprocess.run(args, **kwargs)
    tool = Path(str(args[0])).name
    if tool not in ("ffmpeg", "ffprobe") or cwd is not None:
        raise ValueError("Android media commands require absolute input/output paths")
    payload = json.loads(str(_native_media.execute(tool, json.dumps(list(args[1:])), int(timeout * 1000))))
    if payload.get("timedOut"):
        raise subprocess.TimeoutExpired(args, timeout, output=payload.get("stdout"), stderr=payload.get("stderr"))
    result = subprocess.CompletedProcess(args, payload["returncode"], payload.get("stdout", ""), payload.get("stderr", ""))
    if check:
        result.check_returncode()
    return result


def decrypt_aes_cbc(data, key, iv, *, unpad=False):
    if len(key) != 16 or len(iv) != 16 or not data or len(data) % 16:
        raise ValueError("Invalid AES-128-CBC key, IV or ciphertext length")
    if _native_aes is not None:
        import base64
        result = _native_aes.decrypt(base64.b64encode(data).decode(), base64.b64encode(key).decode(),
                                     base64.b64encode(iv).decode(), bool(unpad))
        return base64.b64decode(str(result), validate=True)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plaintext = decryptor.update(data) + decryptor.finalize()
    if unpad:
        from cryptography.hazmat.primitives.padding import PKCS7
        decoder = PKCS7(128).unpadder()
        plaintext = decoder.update(plaintext) + decoder.finalize()
    return plaintext
