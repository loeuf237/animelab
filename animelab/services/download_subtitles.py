"""Task-scoped subtitle import/search/preview/attachment, independent of video transfer."""
import asyncio
import copy
import tempfile
import threading
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from animelab.config import settings
from animelab.database import init_db
from animelab.models.download_task import DownloadStatus
from animelab.security import is_safe_path
from animelab.services.library_service import library_service
from animelab.services.output_processor import digest, OutputError
from animelab.services.subtitle_imports import unpack, MAX_EXPANDED, filename
from animelab.services.subtitle_service import subtitle_extension
from animelab.services.subtitle_provider import OpenSubtitlesProvider, ProviderError, match_criteria
from animelab.services.subtitle_vault import SubtitleVault
from animelab.services.subdl_provider import SubDLProvider
from animelab.services.subtitle_matching import compare, deduplicate, frame_rate, positive
from animelab.services.subtitle_sync import correct
from animelab.services.media_execution import MediaInterrupted


class DownloadSubtitles:
    def __init__(self, manager, provider=None):
        self.manager = manager
        self.processor = manager.media_pipeline.output_processor
        self.locks = {}
        self.budget = asyncio.Semaphore(2)
        self.results = {}
        self.sync_operations = {}
        if not hasattr(manager, '_subtitle_mutations'):
            manager._subtitle_mutations = set()
        if provider is None:
            init_db()
            provider = OpenSubtitlesProvider(SubtitleVault(settings.DATABASE_PATH, manager.download_dir, settings.CACHE_DIR))
        self.provider = provider
        vault = SubtitleVault(settings.DATABASE_PATH, manager.download_dir, settings.CACHE_DIR, provider='subdl') if getattr(provider, 'vault', None) else None
        self.providers = {'opensubtitles': provider, 'subdl': SubDLProvider(vault)}

    def lock(self, task_id):
        return self.locks.setdefault(task_id, asyncio.Lock())

    @asynccontextmanager
    async def editing(self, task_id):
        async with self.lock(task_id), self.budget:
            self.manager._subtitle_mutations.add(task_id)
            try:
                yield
            finally:
                self.manager._subtitle_mutations.discard(task_id)

    async def blocking(self, function, *args):
        job = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            await job  # Keep mutation ownership until the disk operation stops.
            raise

    def task(self, task_id):
        task = self.manager.get_task(task_id)
        if task is None:
            raise ProviderError('Tâche introuvable', 'task_not_found', 404)
        if (self.manager._export_in_progress(task_id) or task.status in (
                DownloadStatus.DOWNLOADING, DownloadStatus.MUXING, DownloadStatus.PENDING, DownloadStatus.RETRYING)):
            raise ProviderError('Attendez l’arrêt du téléchargement avant de modifier ses sous-titres', 'task_busy', 409)
        if not task.savePath or not is_safe_path(task.savePath, [self.manager.download_dir]) or not Path(task.savePath).is_file():
            raise ProviderError('Une vidéo locale est nécessaire pour ajouter des sous-titres', 'task_media_missing', 409)
        return task

    def context(self, task_id):
        task = self.task(task_id)
        title = task.animeName or Path(task.fileName).stem
        season = re.search(r'(?i)(?:saison\s*(\d+)|\bS(\d{1,3})E)', title + ' ' + task.fileName)
        return dict(query=title, episode=task.episodeNumber, season=int(season[1] or season[2]) if season else None,
                    provider=self.provider.status(), providers={name: value.status() for name, value in self.providers.items()})

    async def video_context(self, task_id):
        result = self.context(task_id)
        async with self.processor.pipeline.inventory_budget:
            _, data = await self.blocking(self.processor.inventory, self.task(task_id))
        stream = next((s for s in data['streams'] if s.get('codec_type') == 'video'), {})
        result['video'] = dict(fps=frame_rate(stream.get('avg_frame_rate')), duration=positive(data.get('format', {}).get('duration')))
        return result

    def get_provider(self, name):
        if name not in self.providers:
            raise ProviderError('Fournisseur de sous-titres inconnu', 'provider_configuration')
        return self.providers[name]

    def _stage(self, task, content, name, encoding, provenance):
        entries = unpack(content, name, encoding)
        info = json.loads(task.mediaJson)
        packages = info.setdefault('subtitleImports', {})
        directory = self.processor.workspace(task) / 'imports'
        directory.mkdir(mode=0o700, exist_ok=True)
        # Expiry is for unselected previews only; attached assets never expire.
        selected = {row.get('importId') for row in info.get('localSubtitleTracks', [])}
        selected.update(package.get('provenance', {}).get('originalImportId') for package in packages.values())
        for key, package in list(packages.items()):
            if key not in selected and time.time() - package.get('created', 0) > 86400:
                for row in package['entries']:
                    path = Path(row['path'])
                    if is_safe_path(path, [directory]):
                        path.unlink(missing_ok=True)
                del packages[key]
        if len(packages) >= 10:
            raise ProviderError('Limite de dix imports par tâche atteinte', 'subtitle_import_limit', 409)
        if shutil.disk_usage(directory).free < MAX_EXPANDED + 16 * 1024 * 1024:
            raise ProviderError('Espace insuffisant pour importer des sous-titres', 'subtitle_disk', 409)
        package_id, created = uuid.uuid4().hex, []
        try:
            stored = []
            for entry in entries:
                entry = dict(entry)
                payload = entry.pop('content')
                entry_id = uuid.uuid4().hex
                path = directory / (entry_id + '.' + entry['format'])
                partial = path.with_suffix('.partial')
                created += [partial, path]
                with partial.open('xb') as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                partial.replace(path)
                entry.update(id=entry_id, path=str(path), sha256=hashlib.sha256(payload).hexdigest())
                # Recompute preview from local bytes, don't keep full text in DB.
                entry.pop('preview', None)
                stored.append(entry)
            packages[package_id] = dict(entries=stored, created=time.time(), provenance=provenance)
            state = info.setdefault('outputState', {})
            state.setdefault('source', task.savePath)
            task.mediaJson = json.dumps(info)
            library_service.save_task(task)
            return self.package(task, package_id)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def package(self, task, package_id):
        package = json.loads(task.mediaJson).get('subtitleImports', {}).get(package_id)
        if not package:
            raise ProviderError('Import introuvable ou expiré', 'subtitle_import_missing', 404)
        result = []
        workspace = self.processor.workspace(task)
        for row in package['entries']:
            path = Path(row['path'])
            if not is_safe_path(path, [workspace]) or not path.is_file() or digest(path) != row['sha256']:
                raise ProviderError('Import local modifié ou introuvable', 'subtitle_import_modified', 409)
            public = {key: value for key, value in row.items() if key not in ('path', 'sha256')}
            with path.open('r', encoding='utf-8') as stream:
                public['preview'] = stream.read(6000)
            result.append(public)
        return dict(importId=package_id, entries=result, provenance=package['provenance'])

    async def upload(self, task_id, content, name, encoding='auto', provenance=None):
        async with self.editing(task_id):
            task = self.task(task_id)
            result = await self.blocking(self._stage, task, content, name, encoding, provenance or {'provider': 'local'})
            return result

    async def attach(self, task_id, import_id, entry_id, language, label, confirmed):
        if not confirmed:
            raise ProviderError('Confirmez la correspondance avec l’épisode avant l’ajout', 'subtitle_episode_confirmation')
        async with self.editing(task_id):
            task = self.task(task_id)
            await self.blocking(self.package, task, import_id)
            info = json.loads(task.mediaJson)
            package = info['subtitleImports'][import_id]
            row = next((entry for entry in package['entries'] if entry['id'] == entry_id), None)
            if row is None:
                raise ProviderError('Fichier de sous-titres introuvable dans cet import', 'subtitle_entry_missing', 404)
            tracks = info.setdefault('localSubtitleTracks', [])
            existing = next((track for track in tracks if track['sha256'] == row['sha256'] and track['lang'] == language
                and bool(track.get('forced')) == bool(package['provenance'].get('forced'))
                and bool(track.get('provenance', {}).get('hearingImpaired')) == bool(package['provenance'].get('hearingImpaired'))), None)
            if existing:
                provenance = existing.setdefault('provenances', [existing['provenance']])
                if package['provenance'] not in provenance:
                    provenance.append(package['provenance'])
                    task.mediaJson = json.dumps(info)
                    library_service.save_task(task)
                return dict(trackId=existing['id'], duplicate=True)
            track_id = 'local:' + uuid.uuid4().hex
            tracks.append(dict(id=track_id, kind='subtitle', importId=import_id, path=row['path'], sha256=row['sha256'],
                format=row['format'], lang=language, label=label or row['name'], sourceFileName=row['name'],
                provenance=package['provenance'], provenances=[package['provenance']], numbering=row.get('numbering'),
                forced=bool(package['provenance'].get('forced'))))
            info['subtitleRevision'] = info.get('subtitleRevision', 0) + 1
            info.setdefault('outputState', {})['completed'] = False
            task.mediaJson = json.dumps(info)
            library_service.save_task(task)
            self.manager.broadcast_update(task)
            return dict(trackId=track_id, duplicate=False)

    def collect_results(self, task_id, query, response, name, video):
        now = time.monotonic()
        results = []
        data = response.get('data', [])
        if not isinstance(data, list):
            raise ProviderError('Résultats de sous-titres invalides', 'provider_response', 502)
        for item in data[:100]:
            if not isinstance(item, dict) or not isinstance(item.get('attributes'), dict):
                raise ProviderError('Résultats OpenSubtitles invalides', 'provider_response', 502)
            attributes = item.get('attributes', {})
            feature = attributes.get('feature_details') or {}
            if not isinstance(feature, dict) or not isinstance(attributes.get('files', []), list):
                raise ProviderError('Résultats OpenSubtitles invalides', 'provider_response', 502)
            checks, warnings = match_criteria(query, feature)
            for file in attributes.get('files', [])[:20]:
                if not isinstance(file, dict):
                    raise ProviderError('Résultats OpenSubtitles invalides', 'provider_response', 502)
                if not ((name == 'opensubtitles' and isinstance(file.get('file_id'), int) and file['file_id'] > 0) or (name == 'subdl' and isinstance(file.get('file_id'), str))):
                    continue
                key = uuid.uuid4().hex
                provenance = dict(provider=name, fileId=file['file_id'],
                    subtitleId=str(item.get('id', ''))[:100], release=str(attributes.get('release', ''))[:300],
                    fps=attributes.get('fps'), duration=attributes.get('duration'), feature={k: feature.get(k) for k in (
                        'title', 'parent_title', 'imdb_id', 'tmdb_id', 'parent_imdb_id', 'parent_tmdb_id', 'season_number', 'episode_number')},
                    checks=checks, warnings=warnings, forced=bool(attributes.get('foreign_parts_only')),
                    hearingImpaired=bool(attributes.get('hearing_impaired')))
                public = dict(id=key, fileName=str(file.get('file_name') or 'subtitle.srt')[:255],
                    language=str(attributes.get('language') or 'und')[:20], release=provenance['release'], fps=provenance['fps'],
                    hearingImpaired=bool(attributes.get('hearing_impaired')), forced=bool(attributes.get('foreign_parts_only')),
                    provider=name, providerIdentity=str(file['file_id']), fingerprint=attributes.get('md5'),
                    duration=positive(attributes.get('duration')), provenances=[provenance],
                    feature=provenance['feature'], checks=checks, warnings=warnings)
                public['checks'] += compare(query, public, video)
                self.results[key] = dict(provider=name, taskId=task_id, fileId=file['file_id'], provenance=provenance,
                                        expires=now + 900, public=public)
                results.append(public)
                if len(results) >= 100:
                    break
            if len(results) >= 100:
                break
        return results

    async def search(self, task_id, query):
        context = await self.video_context(task_id)
        self.results = {key: row for key, row in self.results.items() if row['expires'] > time.monotonic()}
        results, errors, pages = [], [], {}
        for name in query.providers:
            try:
                response = await self.get_provider(name).search(query)
                self.task(task_id)
                results += self.collect_results(task_id, query, response, name, context['video'])
                pages[name] = response.get('total_pages', 1)
            except ProviderError as exc:
                if len(query.providers) == 1:
                    raise
                errors.append(dict(provider=name, code=exc.code, message=str(exc)))
        while len(self.results) > 300:
            self.results.pop(next(iter(self.results)))
        return dict(results=deduplicate(results), errors=errors, page=query.page, totalPages=max(pages.values(), default=1),
                    provider=self.provider.status(), providers={name: value.status() for name, value in self.providers.items()}, video=context['video'])

    async def provider_preview(self, task_id, result_id):
        async with self.editing(task_id):
            task = self.task(task_id)
            row = self.results.get(result_id)
            if not row or row['taskId'] != task_id or row['expires'] <= time.monotonic():
                raise ProviderError('Résultat expiré : relancez la recherche', 'subtitle_result_expired', 409)
            if row.get('importId'):
                return await self.blocking(self.package, task, row['importId'])
            if len(json.loads(task.mediaJson).get('subtitleImports', {})) >= 10:
                raise ProviderError('Limite de dix imports par tâche atteinte', 'subtitle_import_limit', 409)
            content, name = await self.get_provider(row.get('provider', 'opensubtitles')).download(row['fileId'])
            name = filename(name)
            if Path(name).suffix.lower() not in ('.zip', '.gz', '.srt', '.vtt', '.ass', '.ssa'):
                try:
                    name += '.zip' if content.startswith(b'PK\x03\x04') else subtitle_extension(content)
                except ValueError as exc:
                    raise ProviderError('Format OpenSubtitles non pris en charge', 'subtitle_format') from exc
            task = self.task(task_id)
            result = await self.blocking(self._stage, task, content, name, 'auto', row['provenance'])
            row['importId'] = result['importId']
            return result

    def cancel_sync(self, task_id):
        operation = self.sync_operations.get(task_id)
        if not operation:
            return False
        operation['cancel'].set()
        operation['task'].cancelled = True
        return True

    def _correct(self, task, request, operation):
        self.package(task, request.importId)
        info = json.loads(task.mediaJson)
        package = info['subtitleImports'][request.importId]
        entry = next((row for row in package['entries'] if row['id'] == request.entryId), None)
        if not entry:
            raise ProviderError('Fichier de sous-titres introuvable', 'subtitle_entry_missing', 404)
        content = Path(entry['path']).read_bytes()
        reference = None
        with tempfile.TemporaryDirectory(prefix='sync-ref-', dir=self.processor.workspace(task)) as temporary:
            if request.method == 'alass':
                tracks, _ = self.processor.inventory(task)
                track = next((item for item in tracks if item.id == request.referenceTrackId and item.kind == 'subtitle'), None)
                if not track or track.remote:
                    raise ProviderError('Choisissez une piste de référence déjà présente localement', 'subtitle_sync_reference')
                try:
                    selected = self.processor.local_tracks(operation['task'], [track])
                    path = self.processor.text_file(operation['task'], selected[0], Path(temporary))
                except OutputError as exc:
                    raise ProviderError('La référence locale est altérée ou non textuelle ; choisissez une autre piste', 'subtitle_sync_reference', 409) from exc
                reference = (path.read_bytes(), path.suffix)
            output, details = correct(content, '.'+entry['format'], request, reference=reference,
                                      directory=self.processor.workspace(task), cancel=operation['cancel'])
            provenance = dict(package['provenance'])
            provenance.update(originalImportId=provenance.get('originalImportId', request.importId),
                originalEntryId=provenance.get('originalEntryId', request.entryId),
                parentImportId=request.importId, parentEntryId=request.entryId, timingCorrection=details)
            result = self._stage(task, output, 'corrected.'+entry['format'], 'auto', provenance)
            result['comparison'] = details
            result['originalImportId'], result['originalEntryId'] = provenance['originalImportId'], provenance['originalEntryId']
            return result

    async def transform(self, task_id, request):
        async with self.editing(task_id):
            task = self.task(task_id)
            operation_task = copy.copy(task)
            operation_task.paused = operation_task.cancelled = False
            operation = dict(task=operation_task, cancel=threading.Event())
            self.sync_operations[task_id] = operation
            job = asyncio.create_task(self.processor.pipeline.budget.run(operation_task, self.processor.pipeline.jobs,
                self._correct, task, request, operation))
            try:
                return await asyncio.shield(job)
            except asyncio.CancelledError:
                self.cancel_sync(task_id)
                try:
                    await job
                except Exception:
                    pass
                raise
            except MediaInterrupted as exc:
                raise ProviderError('Synchronisation interrompue ; l’original est conservé', 'subtitle_sync_cancelled', 409) from exc
            except ValueError as exc:
                if operation['cancel'].is_set():
                    raise ProviderError('Synchronisation interrompue ; l’original est conservé', 'subtitle_sync_cancelled', 409) from exc
                raise
            finally:
                self.sync_operations.pop(task_id, None)

    async def restore_track(self, task_id, track_id):
        task = self.task(task_id)
        tracks = json.loads(task.mediaJson).get('localSubtitleTracks', [])
        track = next((row for row in tracks if row['id'] == track_id), None)
        source = track.get('provenance', {}) if track else {}
        if not source.get('originalImportId'):
            raise ProviderError('Cette piste ne provient pas d’une correction réversible', 'subtitle_sync_original', 409)
        return await self.attach(task_id, source['originalImportId'], source['originalEntryId'],
                                 track['lang'], track['label']+' · original', True)
