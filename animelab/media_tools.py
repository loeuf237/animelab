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


def native_hardsub_status():
    """Only a successful JNI render probe can enable Android hardsub."""
    unavailable = dict(available=False, reason='Le hardsub Android reste à valider : pont JNI ou libass/libx264 indisponible')
    if not is_native() or not hasattr(_native_media, 'probeHardsub'):
        return unavailable
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix='animelab-p14-') as directory:
            status = json.loads(str(_native_media.probeHardsub(directory)))
        if status.get('available') is True and status.get('renderVerified') is True:
            font = Path(status.get('fontPath', ''))
            if font.is_file() and font.is_absolute():
                return dict(available=True, reason='', fontPath=str(font))
        return dict(available=False, reason='Le hardsub Android reste à valider : essai JNI de rendu non réussi')
    except (OSError, ValueError, RuntimeError, TypeError):
        return unavailable


def which(name):
    if name not in ("ffmpeg", "ffprobe"):
        raise ValueError("Unsupported media tool")
    return name if is_native() else shutil.which(name)


def run(args, *, capture_output=True, text=True, timeout=30, check=False, cwd=None, cancel=None, on_event=None):
    if cancel is not None or on_event is not None:
        from animelab.services.media_execution import run_process, run_native
        kwargs = dict(timeout=timeout, cancel=cancel or (lambda: False),
                      emit=on_event or (lambda event: None), text=text, check=check, cwd=cwd)
        return run_native(_native_media, args, **kwargs) if is_native() else run_process(args, **kwargs)
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


def capabilities():
    """Probe actual tools, not package names or assumed platform features."""
    result = {'native': is_native(), 'ffmpeg': bool(which('ffmpeg')), 'ffprobe': bool(which('ffprobe')),
              'filters': [], 'encoders': [], 'error': None}
    if not result['ffmpeg']:
        return result
    import re
    try:
        for key, flag in (('filters', '-filters'), ('encoders', '-encoders')):
            response = run([which('ffmpeg'), '-hide_banner', flag], timeout=15, check=True)
            result[key] = sorted(set(re.findall(r'^\s*[A-Z.]{2,6}\s+([a-zA-Z0-9_]+)\s', response.stdout, re.M)))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        result['error'] = 'Impossible de détecter les capacités des outils média'
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
