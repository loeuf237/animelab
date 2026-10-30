"""Local output planning, verification and publication (P6/P7).

All network resources enter through SourceHTTP before FFmpeg is invoked. A
private master and a per-task receipt make finalization retryable without video
downloads. No caller-supplied path or FFmpeg expression is accepted in profiles.
"""
from dataclasses import dataclass, replace
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlparse
import httpx

from animelab import media_tools
from animelab.security import is_safe_path, is_safe_url
from animelab.services.download_errors import SubtitleError
from animelab.services.library_service import library_service
from animelab.services.media_contracts import normalize_tracks
from animelab.services.media_execution import MediaInterrupted
from animelab.services.output_profiles import OutputProfile
from animelab.services.subtitle_service import normalize_subtitles, subtitle_extension, subtitle_language
from animelab.services.subtitle_timing import shift, intervals
from animelab.services.source_http import VerificationRequired, RateLimited

TEXT_CODECS = {'ass': '.ass', 'ssa': '.ass', 'subrip': '.srt', 'srt': '.srt',
               'webvtt': '.vtt', 'mov_text': '.srt', 'text': '.srt'}


class OutputError(SubtitleError):
    pass


@dataclass
class LocalTrack:
    id: str
    kind: str
    path: Path
    index: int = 0
    lang: str = 'und'
    label: str = ''
    codec: str = ''
    default: bool = False
    forced: bool = False
    automatic: bool = False
    offset: float = 0
    remote: dict | None = None
    asset: dict | None = None

    def public(self):
        return dict(id=self.id, kind=self.kind, lang=self.lang, label=self.label,
                    format=self.codec, default=self.default, forced=self.forced,
                    automatic=self.automatic, embedded=self.remote is None and self.asset is None,
                    canRestore=bool(self.asset and self.asset.get('provenance', {}).get('originalImportId')),
                    local=not self.remote,
                    provenance=self.asset.get('provenance', {}).get('provider', 'local') if self.asset else 'source' if self.remote else 'embedded')


def digest(path, task=None):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024):
            if task and (task.paused or task.cancelled):
                raise MediaInterrupted('Traitement média interrompu')
            result.update(data)
    return result.hexdigest()


def profile_hash(task):
    revision = json.loads(task.mediaJson).get('subtitleRevision', 0)
    value = task.outputProfileJson + (f'\nsubtitles:{revision}' if revision else '')
    return hashlib.sha256(value.encode()).hexdigest()


def copy_file(task, source, destination):
    with Path(source).open('rb') as incoming, Path(destination).open('wb') as output:
        while data := incoming.read(1024 * 1024):
            if task.paused or task.cancelled:
                raise MediaInterrupted('Copie média interrompue')
            output.write(data)
        output.flush()
        os.fsync(output.fileno())


class OutputProcessor:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.manager = pipeline.manager

    def state(self, task):
        return json.loads(task.mediaJson).get('outputState', {})

    def cleanup(self, task, *, keep_imports=False):
        state = self.state(task)
        if not state.get('source'):
            return
        key = hashlib.sha256(task.id.encode()).hexdigest()[:20]
        directory = Path(state['source']).parent / ('.animelab-media-' + key)
        if is_safe_path(directory, [self.manager.download_dir]) and directory.is_dir():
            if not keep_imports:
                shutil.rmtree(directory)
            else:
                for child in directory.iterdir():
                    if child.name != 'imports':
                        if child.is_dir() and not child.is_symlink():
                            shutil.rmtree(child)
                        else:
                            child.unlink()

    def save_state(self, task, state):
        info = json.loads(task.mediaJson)
        info['outputState'] = state
        task.mediaJson = json.dumps(info)
        library_service.save_task(task)

    def write_receipt(self, task, state):
        directory = self.workspace(task)
        receipt = directory / ('receipt-' + profile_hash(task) + '.json')
        staging = directory / 'receipt.partial'
        with staging.open('w', encoding='utf-8') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        staging.replace(receipt)

    def release_originals(self, task):
        """Retire only this job's inputs, after the published video was verified."""
        state = self.state(task)
        profile = OutputProfile.model_validate_json(task.outputProfileJson)
        if (profile.keepOriginals or not state.get('completed') or state.get('profileHash') != profile_hash(task)
                or task.verificationStatus != 'VALID'):
            return
        artifact = Path(task.savePath)
        published = next((item for item in state.get('published', []) if item['path'] == str(artifact)), None)
        if not published or not artifact.is_file():
            return
        current = artifact.stat()
        if current.st_size != published['size'] or current.st_mtime_ns != published['mtimeNs']:
            return
        directory = self.workspace(task)
        protected = {Path(item['path']).resolve() for item in state['published']}
        source = Path(state['source'])
        # A filename may have been reused by another task or edited by the user.
        # Never remove it merely because it was our initial download pathname.
        if (source.is_file() and not source.is_symlink() and source.resolve() not in protected
                and is_safe_path(source, [self.manager.download_dir])
                and digest(source, task) == state.get('masterHash')):
            source.unlink()
        private = [state.get('master'), *(row.get('path') for row in state.get('resources', {}).values())]
        for name in private:
            if not name:
                continue
            path = Path(name)
            if path.resolve() not in protected and is_safe_path(path, [directory]) and not path.is_symlink():
                path.unlink(missing_ok=True)
        state.update(master=None, masterSize=0, resources={}, originalsDiscarded=True)
        self.write_receipt(task, state)
        self.save_state(task, state)

    def workspace(self, task):
        state = self.state(task)
        source = Path(state.get('source') or task.savePath or '').absolute()
        if not is_safe_path(source, [self.manager.download_dir]):
            raise OutputError('Chemin du média hors du dossier de téléchargements autorisé')
        key = hashlib.sha256(task.id.encode()).hexdigest()[:20]
        directory = source.parent / ('.animelab-media-' + key)
        if not is_safe_path(directory, [self.manager.download_dir]):
            raise OutputError('Dossier de travail non autorisé')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return directory

    def probe(self, path):
        tool = media_tools.which('ffprobe')
        if not tool:
            raise OutputError('FFprobe est requis pour sélectionner et vérifier les pistes')
        with Path(path).open('rb') as source:
            prefix = source.read(512).lstrip(b'\xef\xbb\xbf \r\n\t').lower()
        if prefix.startswith((b'#extm3u', b'ffconcat', b'<?xml', b'<mpd')):
            raise OutputError('Un manifeste ne peut pas être traité comme un fichier média local')
        result = media_tools.run([tool, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format', '-show_streams', '-of', 'json', str(path)],
                                 timeout=30, check=True)
        return json.loads(result.stdout)

    def run(self, task, args, **kwargs):
        protected = []
        for argument in args:
            if argument == '-i':
                protected += ['-protocol_whitelist', 'file,pipe']
            protected.append(str(argument))
        result = self.pipeline._run_media(task, [media_tools.which('ffmpeg'), '-v', 'error', '-y', *protected], **kwargs)
        if result.returncode:
            raise OutputError('FFmpeg a échoué ; les sources sont conservées : ' + (result.stderr or '')[-600:])
        return result

    def ensure_master(self, task):
        state = self.state(task)
        directory = self.workspace(task)
        if state.get('master'):
            master = Path(state['master'])
            if not is_safe_path(master, [directory]) or not master.is_file():
                raise OutputError('Le master local est introuvable ; restauration nécessaire')
            if digest(master, task) != state.get('masterHash'):
                raise OutputError('Le master local a été modifié ; finalisation arrêtée')
            return master
        source = Path(task.savePath)
        if not source.is_file():
            raise OutputError('Vidéo source introuvable')
        data = self.probe(source)
        if not any(s.get('codec_type') == 'video' for s in data['streams']):
            raise OutputError('La source ne contient pas de vidéo')
        size = source.stat().st_size
        self.space(directory, size * 2 + 16 * 1024 * 1024)
        master = directory / ('master' + (source.suffix or '.mkv'))
        staging = directory / 'master.partial'
        try:
            with source.open('rb') as incoming, staging.open('wb') as output:
                while block := incoming.read(1024 * 1024):
                    if task.paused or task.cancelled:
                        raise MediaInterrupted('Préparation du master interrompue')
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            staging.replace(master)
        finally:
            staging.unlink(missing_ok=True)
        state.update(source=str(source), master=str(master), masterHash=digest(master, task),
                     masterSize=size, resources={}, completed=False,
                     inputIsOutput=bool(state.get('originalsDiscarded') or state.get('inputIsOutput')),
                     originalsDiscarded=False)
        task.videoDuration = float(data.get('format', {}).get('duration') or 0) or None
        self.save_state(task, state)
        return master

    @staticmethod
    def space(directory, needed):
        if shutil.disk_usage(directory).free < needed:
            raise OutputError('Espace disque insuffisant ; libérez de la place avant de reprendre')

    def inventory(self, task, *, create_master=False):
        state = self.state(task)
        master = self.ensure_master(task) if create_master else Path(state.get('master') or task.savePath or '')
        if not is_safe_path(master, [self.manager.download_dir]) or not master.is_file():
            raise OutputError('Un fichier vidéo local est nécessaire pour inventorier les pistes')
        probe = self.probe(master)
        tracks = []
        for stream in probe['streams']:
            kind = stream.get('codec_type')
            tags, disposition = stream.get('tags', {}), stream.get('disposition', {})
            if kind == 'video' and disposition.get('attached_pic'):
                continue
            if kind == 'attachment':
                if not str(tags.get('filename', '')).lower().endswith(('.ttf', '.otf', '.ttc')):
                    continue
                kind = 'font'
            if kind not in ('video', 'audio', 'subtitle', 'font'):
                continue
            index = stream['index']
            tracks.append(LocalTrack(id=f'embedded:{kind}:{index}', kind=kind, path=master, index=index,
                lang=tags.get('language', 'und'), label=tags.get('title') or tags.get('filename') or f'{kind} {index}',
                codec=stream.get('codec_name', ''), default=bool(disposition.get('default')),
                forced=bool(disposition.get('forced'))))
        info = json.loads(task.mediaJson)
        subs = normalize_subtitles(task.subtitlesJson, task.downloadPageUrl or task.fileUrl)
        if not subs and task.subtitleUrl:
            subs = normalize_subtitles([{'url': task.subtitleUrl}], task.downloadPageUrl or task.fileUrl)
        external = [] if state.get('originalsDiscarded') or state.get('inputIsOutput') else [
            ('subtitle', subs), ('audio', info.get('audioTracks', []))]
        for kind, values in external:
            for row in normalize_tracks(values, task.downloadPageUrl or task.fileUrl, kind=kind):
                tracks.append(LocalTrack(id=row['id'], kind=kind, path=Path(), lang=row['lang'], label=row['label'],
                    codec=row.get('format', ''), automatic=bool(row.get('automatic')), default=bool(row.get('default')),
                    forced=bool(row.get('forced')), remote=row))
        for row in info.get('localSubtitleTracks', []):
            tracks.append(LocalTrack(id=row['id'], kind='subtitle', path=Path(row['path']),
                lang=row.get('lang', 'und'), label=row.get('label', 'Sous-titres'),
                codec=row['format'], forced=bool(row.get('forced')), asset=row))
        return tracks, probe

    def select(self, task, inventory):
        profile = OutputProfile.model_validate_json(task.outputProfileJson)
        by_id = {track.id: track for track in inventory}
        selected = []
        if profile.selections:
            for selection in profile.selections:
                track = by_id.get(selection.trackId)
                if track is None:
                    if selection.required:
                        raise OutputError('Une piste sélectionnée est absente : ' + selection.trackId)
                    continue
                selected.append(replace(track, offset=selection.offsetSeconds,
                                        default=selection.default, forced=selection.forced))
            selected += [track for track in inventory if track.kind == 'font' and track.id not in {t.id for t in selected}]
        else:
            selected = [track for track in inventory if not track.automatic]
        videos = [track for track in selected if track.kind == 'video']
        if not videos:
            videos = [track for track in inventory if track.kind == 'video'][:1]
            selected = videos + selected
        if len(videos) != 1:
            raise OutputError('Sélectionnez une seule piste vidéo')
        if videos[0].offset:
            raise OutputError('Le décalage vidéo n’est pas pris en charge ; décalez les pistes audio ou de sous-titres')
        if any(t.offset for t in selected if t.kind == 'font'):
            raise OutputError('Le décalage ne s’applique pas aux polices')
        if profile.mode == 'SIDECAR':
            if any(t.kind == 'audio' for t in selected) and profile.selections:
                raise OutputError('Le mode séparé conserve la vidéo et son audio ; choisissez MKV pour les modifier')
            selected = [t for t in selected if t.kind != 'audio'] + [t for t in inventory if t.kind == 'audio' and t.remote is None]
        for kind in ('audio', 'subtitle'):
            candidates = [track for track in selected if track.kind == kind]
            if profile.selections and sum(track.default for track in candidates) > 1:
                raise OutputError('Une seule piste par type peut être définie par défaut')
            if not profile.selections:
                first = next((track for track in candidates if track.default), candidates[0] if candidates else None)
                selected = [replace(t, default=t is first) if t.kind == kind else t for t in selected]
        if profile.mode == 'MP4_HARD':
            subs = [track for track in selected if track.kind == 'subtitle']
            chosen = next((t for t in subs if t.id == profile.burnTrackId), None) if profile.burnTrackId else next((t for t in subs if t.default), subs[0] if subs else None)
            if not chosen:
                raise OutputError('Choisissez une piste de sous-titres disponible pour l’incrustation')
            audio = [track for track in selected if track.kind == 'audio']
            if profile.selections and len(audio) != 1:
                raise OutputError('Le MP4 incrusté requiert une seule piste audio sélectionnée')
            chosen_audio = next((track for track in audio if track.default), audio[0] if audio else None)
            if not chosen_audio:
                raise OutputError('Une piste audio est nécessaire pour le MP4 demandé')
            selected = videos + [chosen_audio, chosen] + [t for t in selected if t.kind == 'font']
        if not any(track.kind == 'audio' for track in selected):
            raise OutputError('Aucune piste audio sélectionnée ; un résultat muet ne sera pas publié')
        return selected

    async def acquire_inputs(self, task):
        # Called while the existing transfer owns its network slot. The final
        # processor only uses local, validated paths.
        task.phase = 'preparing_output'
        self.manager.scheduler.release_network(task.id)
        tracks, _ = await self.pipeline.budget.run(task, self.pipeline.jobs, self.inventory, task, create_master=True)
        selected = self.select(task, tracks)
        directory = self.workspace(task)
        state = self.state(task)
        for track in selected:
            if track.remote is None:
                continue
            row = track.remote
            key = hashlib.sha256(track.id.encode()).hexdigest()[:24]
            cached = state['resources'].get(track.id)
            if cached:
                path = Path(cached['path'])
                if is_safe_path(path, [directory]) and path.is_file() and await asyncio.to_thread(digest, path, task) == cached['sha256']:
                    continue
            url = row['url']
            if not is_safe_url(url) or urlparse(url).path.lower().endswith(('.m3u8', '.mpd')):
                raise OutputError('Cette piste externe nécessite un transfert segmenté non encore disponible')
            limit = 10 * 1024 * 1024 if track.kind == 'subtitle' else 2 * 1024 ** 3
            headers = dict(row.get('headers') or {})
            if row.get('referer'):
                headers.setdefault('Referer', row['referer'])
            origin = urlparse(task.directDownloadUrl or task.fileUrl or '')
            target = urlparse(url)
            if (origin.scheme, origin.netloc) == (target.scheme, target.netloc):
                headers = {**task.requestHeaders, **headers}
            async def validate(request):
                if not is_safe_url(str(request.url)):
                    raise OutputError('Redirection de piste non autorisée')
            staging = directory / (key + '.partial')
            try:
                async with self.manager.scheduler.resource_network(task), self.manager._create_async_client(headers=headers, timeout=45) as client:
                    task.phase = 'subtitles' if track.kind == 'subtitle' else 'audio'
                    task.throttleStartTimeMs = 0
                    self.manager.broadcast_update(task)
                    client.event_hooks.setdefault('request', []).append(validate)
                    async with client.stream('GET', url) as response:
                        response.raise_for_status()
                        if 'text/html' in response.headers.get('content-type', ''):
                            raise OutputError('La piste reçue est une page HTML')
                        size = 0
                        fingerprint = hashlib.sha256()
                        with staging.open('wb') as output:
                            async for block in response.aiter_bytes(65536):
                                if task.paused or task.cancelled:
                                    raise MediaInterrupted('Récupération de piste interrompue')
                                size += len(block)
                                if size > limit:
                                    raise OutputError('Piste externe trop volumineuse')
                                output.write(block)
                                fingerprint.update(block)
                                await self.manager._apply_throttle(task, len(block))
                            output.flush()
                            os.fsync(output.fileno())
                if size == 0:
                    raise OutputError('Piste externe vide')
                extension = subtitle_extension(staging.read_bytes()) if track.kind == 'subtitle' else '.audio'
                path = directory / (key + extension)
                staging.replace(path)
                if track.kind == 'audio' and not any(s.get('codec_type') == 'audio' for s in (await asyncio.to_thread(self.probe, path))['streams']):
                    raise OutputError('La ressource reçue ne contient pas de piste audio')
                state['resources'][track.id] = dict(path=str(path), sha256=fingerprint.hexdigest())
                self.save_state(task, state)
            except (VerificationRequired, RateLimited, MediaInterrupted, OutputError):
                raise
            except httpx.HTTPStatusError as exc:
                raise SubtitleError(f'Récupération de piste : HTTP {exc.response.status_code}',
                                    refresh_required=exc.response.status_code in (401, 403, 404, 410)) from exc
            except httpx.RequestError as exc:
                raise OutputError('Connexion interrompue pendant la récupération d’une piste ; le master est conservé') from exc
            finally:
                staging.unlink(missing_ok=True)

    def local_tracks(self, task, selected):
        state = self.state(task)
        result = []
        for track in selected:
            if track.asset is not None:
                if (not is_safe_path(track.path, [self.workspace(task)]) or not track.path.is_file()
                        or digest(track.path, task) != track.asset['sha256']):
                    raise OutputError('Un sous-titre importé a été modifié ou supprimé')
            if track.remote is not None:
                asset = state['resources'].get(track.id)
                if not asset:
                    raise OutputError('Une piste externe sélectionnée n’a pas été récupérée')
                path = Path(asset['path'])
                if not is_safe_path(path, [self.workspace(task)]) or digest(path, task) != asset['sha256']:
                    raise OutputError('Une piste locale a été modifiée')
                if track.kind == 'audio':
                    audio = next(s for s in self.probe(path)['streams'] if s['codec_type'] == 'audio')
                    track = replace(track, path=path, index=audio['index'], codec=audio['codec_name'])
                else:
                    track = replace(track, path=path, codec=path.suffix.lstrip('.'))
            result.append(track)
        return result

    def text_file(self, task, track, directory):
        if track.remote is None and track.asset is None:
            extension = TEXT_CODECS.get(track.codec)
            if extension is None:
                raise OutputError('Sous-titres bitmap ou format non textuel : conversion/OCR non disponible')
            path = directory / (hashlib.sha256(track.id.encode()).hexdigest()[:16] + extension)
            self.run(task, ['-copyts', '-i', track.path, '-map', f'0:{track.index}', '-c:s', 'ass' if extension == '.ass' else 'srt' if extension == '.srt' else 'webvtt', path])
            content = path.read_bytes()
        else:
            extension = subtitle_extension(track.path.read_bytes())
            content = track.path.read_bytes()
        path = directory / (hashlib.sha256(track.id.encode()).hexdigest()[:16] + '.shifted' + extension)
        path.write_bytes(shift(content, track.offset, extension))
        return path

    def fonts(self, task, selected, directory):
        result = []
        for track in selected:
            if track.kind != 'font':
                continue
            path = directory / f'font-{track.index}.ttf'
            self.run(task, [f'-dump_attachment:{track.index}', path, '-i', track.path,
                '-map', '0:v:0', '-c:v', 'copy', '-t', '0', '-f', 'null', '-'])
            if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024 or path.read_bytes()[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'ttcf', b'true'):
                raise OutputError('Police jointe absente ou invalide')
            if path.read_bytes()[:4] == b'OTTO':
                destination = path.with_suffix('.otf')
                path.replace(destination)
                path = destination
            result.append(path)
        return result

    def ready(self, task):
        state = self.state(task)
        if not state.get('completed') or state.get('profileHash') != profile_hash(task):
            return False
        for artifact in state.get('published', []):
            path = Path(artifact['path'])
            if (not is_safe_path(path, [self.manager.download_dir]) or not path.is_file()
                    or path.stat().st_size != artifact.get('size') or path.stat().st_mtime_ns != artifact.get('mtimeNs')):
                return False
        return bool(state.get('published'))

    def recover(self, task):
        directory = self.workspace(task)
        receipt = directory / ('receipt-' + profile_hash(task) + '.json')
        if not receipt.exists():
            return False
        try:
            state = json.loads(receipt.read_text())
        except (ValueError, OSError) as exc:
            raise OutputError('Le reçu de finalisation est invalide ; les fichiers sources sont conservés') from exc
        if state.get('taskId') != task.id or state.get('profileHash') != profile_hash(task):
            return False
        for artifact in state.get('published', []):
            path = Path(artifact['path'])
            if not is_safe_path(path, [self.manager.download_dir]) or not path.is_file() or digest(path, task) != artifact['sha256']:
                return False
        if state.get('master'):
            master = Path(state['master'])
            if master.is_file():
                if not is_safe_path(master, [directory]) or digest(master, task) != state['masterHash']:
                    return False
            elif OutputProfile.model_validate_json(task.outputProfileJson).keepOriginals:
                return False
        self.adopt(task, state)
        return True

    def adopt(self, task, state):
        task.savePath = state['artifact']
        task.fileName = Path(task.savePath).name
        task.totalBytes = task.downloadedBytes = Path(task.savePath).stat().st_size
        paths = [track['path'] for track in state.get('sidecarTracks', [])]
        task.savePathSubtitle = json.dumps(paths) if paths else None
        self.save_state(task, state)

    def process(self, task):
        if self.recover(task):
            return
        master = self.ensure_master(task)
        profile = OutputProfile.model_validate_json(task.outputProfileJson)
        inventory, data = self.inventory(task)
        selected = self.local_tracks(task, self.select(task, inventory))
        directory = self.workspace(task)
        state = self.state(task)
        self.space(directory, sum(t.path.stat().st_size for t in selected if t.kind in ('video', 'audio')) + 32 * 1024 * 1024)
        source = Path(state['source'])
        published = []
        warnings = []
        with tempfile.TemporaryDirectory(prefix='finalize-', dir=directory) as temporary:
            work = Path(temporary)
            subs = [(track, None if profile.mode == 'MKV_SOFT' and track.remote is None and track.asset is None and track.codec not in TEXT_CODECS
                     else self.text_file(task, track, work)) for track in selected if track.kind == 'subtitle']
            font_paths = self.fonts(task, selected, work)
            if profile.mode == 'SIDECAR':
                if not subs:
                    raise OutputError('Aucun sous-titre sélectionné pour la sortie séparée')
                staging = work / ('video' + master.suffix)
                copy_file(task, master, staging)
                outputs = [(staging, source.with_name(source.stem + '.sidecar' + master.suffix))]
                for track, path in subs:
                    subtitle_extension(path.read_bytes())
                    name = f'{source.stem}.{subtitle_language(track.lang)}.{hashlib.sha256(track.id.encode()).hexdigest()[:8]}'
                    outputs.append((path, source.with_name(name + path.suffix)))
                outputs += [(font, source.with_name(source.stem + '.' + font.name)) for font in font_paths]
                provenance = work / 'subtitles.json'
                provenance.write_text(json.dumps({'version': 1, 'tracks': [dict(id=track.id, label=track.label,
                    language=track.lang, offsetSeconds=track.offset, format=path.suffix.lstrip('.'),
                    origin=track.asset.get('provenance') if track.asset else 'source' if track.remote else 'embedded',
                    sha256=digest(path, task)) for track, path in subs]}, ensure_ascii=False, indent=2), encoding='utf-8')
                outputs.append((provenance, source.with_name(source.stem + '.subtitles.json')))
            else:
                suffix = '.mp4' if profile.mode == 'MP4_HARD' else '.mkv'
                staging = work / ('output' + suffix)
                target = source.with_suffix(suffix)
                if target == source:
                    target = source.with_name(source.stem + ('.hardsub' if suffix == '.mp4' else '.subtitled') + suffix)
                video = next(track for track in selected if track.kind == 'video')
                args = ['-i', str(master)]
                audio_maps = []
                audio = [track for track in selected if track.kind == 'audio']
                for track in audio:
                    input_index = 1 + len(audio_maps)
                    args += ['-itsoffset', str(track.offset), '-i', str(track.path)]
                    audio_maps.append(f'{input_index}:{track.index}')
                sub_maps = []
                for track, path in subs:
                    input_index = 1 + len(audio_maps) + len(sub_maps)
                    if path is None:
                        args += ['-itsoffset', str(track.offset), '-i', str(track.path)]
                        sub_maps.append(f'{input_index}:{track.index}')
                    else:
                        args += ['-i', str(path)]
                        sub_maps.append(f'{input_index}:s:0')
                args += ['-map', f'0:{video.index}']
                for mapping in audio_maps:
                    args += ['-map', mapping]
                for index, track in enumerate(audio):
                    args += [f'-metadata:s:a:{index}', 'language=' + subtitle_language(track.lang),
                             f'-metadata:s:a:{index}', 'title=' + track.label,
                             f'-disposition:a:{index}', '+'.join(flag for flag, active in [('default', track.default), ('forced', track.forced)] if active) or '0']
                if profile.mode == 'MKV_SOFT':
                    # FFmpeg 4.4 defaults to inferring FlagDefault for the first
                    # track of each kind, even after an explicit disposition=0.
                    args += ['-default_mode', 'passthrough', '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy']
                    for index, ((track, path), mapping) in enumerate(zip(subs, sub_maps)):
                        args += ['-map', mapping, f'-metadata:s:s:{index}', 'language=' + subtitle_language(track.lang),
                                 f'-metadata:s:s:{index}', 'title=' + track.label,
                                 f'-disposition:s:{index}', '+'.join(flag for flag, active in [('default', track.default), ('forced', track.forced)] if active) or '0']
                        if path is not None and path.suffix == '.vtt':
                            args += [f'-c:s:{index}', 'srt']
                            warnings.append('Conversion WebVTT vers SRT : certaines mises en forme peuvent être simplifiées')
                    for index, font in enumerate(font_paths):
                        mime = 'application/vnd.ms-opentype' if font.suffix == '.otf' else 'application/x-truetype-font'
                        args += ['-attach', str(font), f'-metadata:s:t:{index}', 'mimetype=' + mime,
                                 f'-metadata:s:t:{index}', 'filename=' + font.name]
                    args += [str(staging)]
                    self.run(task, args)
                else:
                    native_status = None
                    if media_tools.is_native():
                        native_status = media_tools.native_hardsub_status()
                        if not native_status['available']:
                            raise OutputError(native_status['reason'])
                        video_stream = next(s for s in data['streams'] if s.get('index') == video.index)
                        if (not video_stream.get('width') or not video_stream.get('height') or
                                max(video_stream['width'], video_stream['height']) > 1920 or
                                min(video_stream['width'], video_stream['height']) > 1080 or
                                not float(data.get('format', {}).get('duration') or 0) or
                                float(data['format']['duration']) > 10800):
                            raise OutputError('Hardsub Android limité à 1080p et trois heures avec durée connue')
                    burn_path = work / ('burn' + subs[0][1].suffix)
                    shutil.copyfile(subs[0][1], burn_path)
                    duration = float(data.get('format', {}).get('duration') or 0)
                    if not any(end > 0 and (not duration or start < duration) for start, end in intervals(burn_path.read_bytes(), burn_path.suffix)):
                        raise OutputError('Les sous-titres sélectionnés sont vides ou hors de la durée de la vidéo')
                    fonts = work / 'fonts'
                    fonts.mkdir()
                    for font in font_paths:
                        shutil.copyfile(font, fonts / font.name)
                    if native_status:
                        from animelab.services.android_hardsub import subtitle_filter
                        shutil.copyfile(native_status['fontPath'], fonts / 'system-font.ttf')
                        vf = subtitle_filter(burn_path, fonts)
                    else:
                        vf = f'subtitles=filename={burn_path.name}:fontsdir=fonts'
                    args += ['-vf', vf,
                             '-xerror',
                             '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
                             '-c:a', 'copy' if audio[0].codec == 'aac' else 'aac', '-sn', '-dn', '-map_metadata', '-1', '-movflags', '+faststart']
                    if native_status:
                        args += ['-threads', '1', '-filter_threads', '1']
                    if duration > 0:
                        args += ['-t', str(duration)]
                    args += [str(staging)]
                    kwargs = {} if native_status else dict(cwd=work)
                    self.run(task, args, timeout=max(300, min(86400, duration * 12 + 120)), **kwargs)
                    if not font_paths:
                        warnings.append('Aucune police n’est jointe : le rendu utilise une police du système')
                self.verify_output(task, staging, selected, data, profile.mode)
                outputs = [(staging, target)]
            if task.paused or task.cancelled:
                raise MediaInterrupted('Publication interrompue')
            try:
                for staged, target in outputs:
                    if task.paused or task.cancelled:
                        raise MediaInterrupted('Publication interrompue')
                    fingerprint = digest(staged, task)
                    destination = self.manager._publish_mux_file(staged, master, target, task.id)
                    published.append(dict(path=str(destination), sha256=fingerprint,
                                          size=destination.stat().st_size, mtimeNs=destination.stat().st_mtime_ns))
                sidecar_tracks = [dict(id=track.id, path=published[index + 1]['path'], lang=track.lang,
                    label=track.label, default=track.default, forced=track.forced)
                    for index, (track, path) in enumerate(subs)] if profile.mode == 'SIDECAR' else []
                state.update(taskId=task.id, profileHash=profile_hash(task), artifact=published[0]['path'],
                    sidecars=[item['path'] for item in published[1:]], published=published,
                    sidecarTracks=sidecar_tracks, warnings=warnings, completed=True)
                self.write_receipt(task, state)
                self.adopt(task, state)
            except BaseException:
                for artifact in published:
                    Path(artifact['path']).unlink(missing_ok=True)
                raise

    def verify_output(self, task, path, selected, master_data, mode):
        result = self.probe(path)
        streams = result['streams']
        for kind in ('video', 'audio', 'subtitle'):
            expected = sum(t.kind == kind for t in selected) if mode == 'MKV_SOFT' or kind != 'subtitle' else 0
            if len([s for s in streams if s['codec_type'] == kind]) != expected:
                raise OutputError('Nombre de pistes incorrect après traitement : ' + kind)
        if mode == 'MP4_HARD':
            if next(s for s in streams if s['codec_type'] == 'video')['codec_name'] != 'h264':
                raise OutputError('Le résultat hardsub n’est pas une vidéo H.264')
            if next(s for s in streams if s['codec_type'] == 'audio')['codec_name'] != 'aac':
                raise OutputError('Le résultat hardsub ne contient pas l’audio AAC attendu')
        for kind in ('audio', 'subtitle'):
            expected = [track for track in selected if track.kind == kind]
            actual = [stream for stream in streams if stream['codec_type'] == kind]
            for track, stream in zip(expected, actual):
                if subtitle_language(stream.get('tags', {}).get('language')) != subtitle_language(track.lang):
                    raise OutputError('Langue incorrecte après traitement')
                if mode == 'MKV_SOFT' and (bool(stream.get('disposition', {}).get('default')) != track.default
                        or bool(stream.get('disposition', {}).get('forced')) != track.forced):
                    raise OutputError('Disposition de piste incorrecte après traitement')
        if mode == 'MKV_SOFT' and len([s for s in streams if s['codec_type'] == 'attachment']) != sum(t.kind == 'font' for t in selected):
            raise OutputError('Polices manquantes après fusion')
        source_duration = float(master_data.get('format', {}).get('duration') or 0)
        duration = float(result.get('format', {}).get('duration') or 0)
        if source_duration and abs(duration - source_duration) > max(2, source_duration * .03):
            raise OutputError('Durée incorrecte après traitement')
        self.run(task, ['-xerror', '-i', path, '-map', '0:v:0', '-map', '0:a?', '-t', '2', '-f', 'null', '-'])
