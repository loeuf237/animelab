"""Bounded, non-extracting subtitle uploads. Archive member names never become paths."""
import gzip
import io
from pathlib import PurePosixPath
import re
import stat
from zipfile import BadZipFile, ZipFile, ZIP_STORED, ZIP_DEFLATED

from animelab.services.subtitle_provider import MAX_FILE, ProviderError
from animelab.services.subtitle_service import subtitle_extension
from animelab.services.subtitle_timing import intervals

MAX_MEMBERS = 100
MAX_EXPANDED = 30 * 1024 * 1024
EXTENSIONS = {'.srt', '.vtt', '.ass', '.ssa'}


def filename(value):
    name = str(value).replace('\\', '/')
    parts = PurePosixPath(name).parts
    if (not name or len(name) > 255 or name.startswith('/') or any(part in ('..', '') for part in parts)
            or ':' in name or any(ord(char) < 32 for char in name)):
        raise ProviderError('Nom de fichier d’archive non autorisé', 'subtitle_archive')
    return name


def parse_text(content, name, encoding='auto'):
    if not content or len(content) > MAX_FILE:
        raise ProviderError('Sous-titre vide ou supérieur à 10 Mo', 'subtitle_size')
    if PurePosixPath(name).suffix.lower() not in EXTENSIONS:
        raise ProviderError('Format attendu : SRT, VTT ou ASS', 'subtitle_format')
    codec = {'auto': 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig',
             'utf-8': 'utf-8-sig', 'windows-1252': 'cp1252', 'iso-8859-1': 'iso-8859-1'}.get(encoding)
    if not codec:
        raise ProviderError('Encodage non pris en charge', 'subtitle_encoding')
    try:
        text = content.decode(codec).replace('\r\n', '\n').replace('\r', '\n')
        if text.lstrip().lower().startswith(('<!doctype', '<html', '<?xml')):
            raise ValueError()
        if '\x00' in text or any(ord(char) < 32 and char not in '\n\t' for char in text):
            raise ValueError()
        data = text.encode('utf-8')
        extension = subtitle_extension(data)
        times = intervals(data, extension)
        if not times or len(times) > 100000:
            raise ValueError()
        if any(start < 0 or end > 864000 or end <= start for start, end in times):
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise ProviderError('Sous-titre invalide ou encodage incorrect ; choisissez son encodage d’origine', 'subtitle_encoding') from exc
    match = re.search(r'(?i)(?:\bS(\d{1,3})[ ._-]*E(\d{1,5})\b|\b(\d{1,3})x(\d{1,5})\b)', name)
    episode = dict(season=int(match[1] or match[3]), episode=int(match[2] or match[4])) if match else None
    return dict(name=name, content=data, format=extension.lstrip('.'), size=len(data), cues=len(times),
                firstCue=min(start for start, end in times), lastCue=max(end for start, end in times),
                preview=text[:6000], numbering=episode)


def unpack(content, name, encoding='auto'):
    name = filename(name)
    if len(content) > MAX_FILE:
        raise ProviderError('Import limité à 10 Mo compressés', 'subtitle_size', 413)
    result = []
    if name.lower().endswith('.zip'):
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > MAX_MEMBERS:
                    raise ProviderError('Archive limitée à 100 entrées', 'subtitle_archive')
                total, seen = 0, set()
                for entry in members:
                    member = filename(entry.filename)
                    mode = entry.external_attr >> 16
                    if (entry.flag_bits & 1 or stat.S_ISLNK(mode) or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                            or member in seen or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))):
                        raise ProviderError('Archive chiffrée, lien ou entrée spéciale non autorisée', 'subtitle_archive')
                    seen.add(member)
                    if entry.is_dir():
                        continue
                    total += entry.file_size
                    if entry.file_size > MAX_FILE or total > MAX_EXPANDED or entry.file_size > max(4096, entry.compress_size * 200):
                        raise ProviderError('Archive décompressée trop volumineuse', 'subtitle_archive')
                    if PurePosixPath(member).suffix.lower() not in EXTENSIONS:
                        continue
                    with archive.open(entry) as stream:
                        data = stream.read(MAX_FILE + 1)
                    result.append(parse_text(data, member, encoding))
        except (BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError) as exc:
            raise ProviderError('Archive ZIP endommagée ou non prise en charge', 'subtitle_archive') from exc
    elif name.lower().endswith('.gz'):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                data = stream.read(MAX_FILE + 1)
            if len(data) > max(4096, len(content) * 200):
                raise ProviderError('Archive décompressée trop volumineuse', 'subtitle_archive')
            result = [parse_text(data, name[:-3], encoding)]
        except (OSError, EOFError) as exc:
            raise ProviderError('Archive GZIP endommagée', 'subtitle_archive') from exc
    else:
        result = [parse_text(content, name, encoding)]
    if not result:
        raise ProviderError('Aucun sous-titre SRT/VTT/ASS dans l’archive', 'subtitle_format')
    return result
