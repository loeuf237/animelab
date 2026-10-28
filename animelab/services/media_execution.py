"""Bounded, cancellable media processes. No shell, no ownership of input files."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import uuid

from animelab.services.media_contracts import MediaEvent

MAX_OUTPUT = 2 * 1024 * 1024


class MediaInterrupted(RuntimeError):
    pass


class WindowsProcessJob:
    """Kill descendants even if their parent already exited (Windows 8+)."""
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes
        size = ctypes.c_size_t
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', wintypes.DWORD), ('minimum', size), ('maximum', size),
                        ('active', wintypes.DWORD), ('affinity', size),
                        ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('read', 'write', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', Counters), ('process_memory', size),
                        ('job_memory', size), ('peak_process', size), ('peak_job', size)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api = api
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle)))):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def terminate(self):
        self.api.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def _stop(process):
    if os.name == 'nt':
        job = getattr(process, '_media_job', None)
        if job:
            job.terminate()
            process.wait(timeout=5)
            return
        if process.poll() is not None:
            return
        # A new process group alone does not make terminate() kill descendants.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=10, check=False,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait(timeout=5)
    if os.name != 'nt':
        # A descendant may ignore TERM even after the group leader has exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process(args, *, timeout, cancel, emit, text=True, check=False, cwd=None):
    args = [str(arg) for arg in args]
    if not args or timeout <= 0:
        raise ValueError('Commande média ou délai invalide')
    if cancel():
        raise MediaInterrupted('Traitement média interrompu')
    options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
               if os.name == 'nt' else {'start_new_session': True})
    # FFmpeg progress goes to stdout. Keep all network activity in SourceHTTP;
    # this runner is used for local assembly/finalization only.
    process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    if os.name == 'nt':
        try:
            process._media_job = WindowsProcessJob(process)
        except BaseException:
            _stop(process)
            process.stdout.close()
            process.stderr.close()
            raise
    messages = queue.Queue(maxsize=128)
    finished = threading.Event()

    def read(stream, index):
        try:
            while not finished.is_set():
                data = stream.read1(4096)
                if not data:
                    break
                while not finished.is_set():
                    try:
                        messages.put((index, data), timeout=.1)
                        break
                    except queue.Full:
                        continue
        finally:
            stream.close()
            while not finished.is_set():
                try:
                    messages.put((index, None), timeout=.1)
                    break
                except queue.Full:
                    continue

    readers = [threading.Thread(target=read, args=(stream, index), daemon=True)
               for index, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    output, progress_buffer, closed = [bytearray(), bytearray()], b'', 0
    deadline = time.monotonic() + timeout
    try:
        emit(MediaEvent('started'))
        while closed < 2 or process.poll() is None:
            if cancel():
                emit(MediaEvent('stopped'))
                raise MediaInterrupted('Traitement média interrompu')
            if time.monotonic() >= deadline:
                # Do not include argv/URLs/cookies in the exception payload.
                raise subprocess.TimeoutExpired(['media-tool'], timeout)
            try:
                index, data = messages.get(timeout=.05)
            except queue.Empty:
                continue
            if data is None:
                closed += 1
                continue
            output[index].extend(data)
            if sum(map(len, output)) > MAX_OUTPUT:
                raise RuntimeError('Limite de diagnostics média dépassée')
            if index == 0:
                progress_buffer += data
                while b'\n' in progress_buffer:
                    line, progress_buffer = progress_buffer.split(b'\n', 1)
                    if line.startswith(b'out_time_us='):
                        try:
                            emit(MediaEvent('encoding', media_seconds=max(0, int(line.split(b'=')[1])) / 1_000_000))
                        except ValueError:
                            pass
                if len(progress_buffer) > 65536:
                    progress_buffer = b''
        result = subprocess.CompletedProcess(['media-tool'], process.returncode,
            *(bytes(value).decode('utf-8', errors='replace') if text else bytes(value) for value in output))
        if check:
            result.check_returncode()
        return result
    finally:
        try:
            _stop(process)
        finally:
            job = getattr(process, '_media_job', None)
            if job:
                job.close()
            finished.set()
            for reader in readers:
                reader.join(timeout=2)


def run_native(bridge, args, *, timeout, cancel, emit, text=True, check=False, cwd=None):
    if cwd is not None or Path(str(args[0])).stem not in ('ffmpeg', 'ffprobe'):
        raise ValueError('Commande JNI invalide')
    if not all(hasattr(bridge, name) for name in ('executeManaged', 'pollManaged', 'cancelManaged', 'releaseManaged')):
        raise RuntimeError('Le pont média Android doit être mis à jour pour la supervision')
    identity = str(uuid.uuid4())
    done = threading.Event()
    payload = []
    errors = []

    def execute():
        try:
            payload.append(json.loads(str(bridge.executeManaged(Path(str(args[0])).stem,
                json.dumps(list(args[1:])), int(timeout * 1000), identity))))
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    if cancel():
        raise MediaInterrupted('Traitement média interrompu')
    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    interrupted = False
    emit_error = None
    last_seconds = None
    deadline = time.monotonic() + timeout
    try:
        while not done.wait(.05):
            interrupted = interrupted or cancel()
            if interrupted or time.monotonic() >= deadline or emit_error:
                bridge.cancelManaged(identity)
            try:
                state = json.loads(str(bridge.pollManaged(identity)))
                if state.get('seconds') is not None and state['seconds'] != last_seconds and not emit_error:
                    emit(MediaEvent('encoding', media_seconds=state['seconds']))
                    last_seconds = state['seconds']
            except Exception as exc:
                emit_error = exc
        if errors:
            raise RuntimeError('Échec du pont média JNI') from errors[0]
        if emit_error:
            raise emit_error
        if interrupted or cancel():
            raise MediaInterrupted('Traitement média interrompu')
        data = payload[0]
        if data.get('timedOut') or time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(['native-media'], timeout)
        result = subprocess.CompletedProcess(['native-media'], data['returncode'],
            data.get('stdout', ''), data.get('stderr', ''))
        if not text:
            result.stdout, result.stderr = result.stdout.encode(), result.stderr.encode()
        if check:
            result.check_returncode()
        return result
    finally:
        bridge.releaseManaged(identity)
