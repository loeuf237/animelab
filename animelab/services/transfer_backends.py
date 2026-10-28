"""Adapters for existing transfers. The scheduler and retry loop retain ownership."""
from dataclasses import dataclass
import hashlib
import json
import uuid

from animelab.services.media_contracts import (
    BackendCapabilities, MediaEvent, ResolvedMedia, TransferResult, UnsupportedMedia,
)
from animelab.services.library_service import library_service
from animelab.services.download_resume import media_resource


@dataclass
class NativeBackend:
    manager: object
    name: str
    method: str
    capabilities: BackendCapabilities

    async def transfer(self, task, media, emit):
        emit(MediaEvent('started'))
        target = list(media.chunks) if media.protocol == 'chunks' else media.url
        await getattr(self.manager, self.method)(task, target)
        complete = task.status.value == 'COMPLETED'
        emit(MediaEvent('checkpoint', bytes_received=task.downloadedBytes))
        return TransferResult(self.name, task.savePath or '', complete,
                              {'bytes': task.downloadedBytes, 'path': task.savePath})


class TransferPlanner:
    def __init__(self, manager):
        self.manager = manager
        self.backends = [
            NativeBackend(manager, 'http-range', '_download_single_file', BackendCapabilities(frozenset({'http'}))),
            NativeBackend(manager, 'hls-native', '_download_hls_stream', BackendCapabilities(frozenset({'hls'}), frozenset({'aes128'}))),
            NativeBackend(manager, 'mytv-chunks', '_download_mytv_chunks', BackendCapabilities(frozenset({'chunks'}))),
        ]

    def select(self, media: ResolvedMedia, profile=None):
        # Audio listed separately may be optional alternate audio. Only the
        # resolver's explicit requirement (video-only format) mandates assembly.
        if (media.protocol == 'http' and media.requirements == frozenset({'separate_audio'})
                and profile and profile.get('mode') in ('MKV_SOFT', 'MP4_HARD') and profile.get('strict')):
            return self.backends[0]
        for backend in self.backends:
            if backend.capabilities.accepts(media):
                return backend
        raise UnsupportedMedia('Aucun moteur compatible avec les pistes et le format demandés')

    async def transfer(self, task, media: ResolvedMedia):
        backend = self.select(media, json.loads(task.outputProfileJson))
        info = json.loads(task.mediaJson)
        previous = info.get('transferAttempt')
        if previous and previous['backend'] != backend.name and previous['status'] != 'completed':
            raise UnsupportedMedia('Reprise avec un autre moteur refusée : conservez ou réinitialisez explicitement les fragments')
        attempt = dict(id=str(uuid.uuid4()), backend=backend.name, version='native-v1',
            representation=hashlib.sha256(str(media_resource(media.url)).encode()).hexdigest(),
            status='running', checkpoint_json=json.dumps({'path': task.savePath, 'bytes': task.downloadedBytes}))
        info['transferAttempt'] = attempt
        task.mediaJson = json.dumps(info)
        library_service.save_task(task)
        try:
            def emit(event):
                if event.kind == 'checkpoint':
                    attempt['checkpoint_json'] = json.dumps({'path': task.savePath, 'bytes': event.bytes_received})
            result = await backend.transfer(task, media, emit)
            attempt['status'] = ('completed' if result.complete else 'failed'
                                 if task.status.value == 'FAILED' else 'interrupted')
            attempt['checkpoint_json'] = json.dumps(result.checkpoint)
            return result
        except BaseException:
            attempt['status'] = 'interrupted' if task.paused or task.cancelled else 'failed'
            raise
        finally:
            # A resolver can refresh inventory during a retry: keep its fields.
            info = json.loads(task.mediaJson)
            info['transferAttempt'] = attempt
            task.mediaJson = json.dumps(info)
            library_service.save_task(task)
