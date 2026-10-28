"""Reversible timing edits and optional alass v2.0.0 on local subtitle references.

alass receives generated timing-only SRT files, never a URL, a video, credentials
or a caller-supplied command. Its timings are applied back to the original text
so ASS styles and VTT headers are not rewritten by an external parser.
"""
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
import threading

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from animelab import media_tools
from animelab.services.media_execution import run_process, MediaInterrupted
from animelab.services.subtitle_provider import ProviderError
from animelab.services.subtitle_timing import intervals, shift, stamp
from animelab.services.subtitle_imports import parse_text


class TimingCorrection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    importId: str = Field(pattern=r'^[0-9a-f]{32}$')
    entryId: str = Field(pattern=r'^[0-9a-f]{32}$')
    method: Literal['manual', 'alass'] = 'manual'
    offsetSeconds: float = Field(default=0, ge=-86400, le=86400)
    sourceFps: float | None = Field(default=None, ge=1, le=240)
    targetFps: float | None = Field(default=None, ge=1, le=240)
    referenceTrackId: str | None = Field(default=None, max_length=128)
    referenceConfirmed: bool = False
    allowSplits: bool = False

    @model_validator(mode='after')
    def consistent(self):
        if bool(self.sourceFps) != bool(self.targetFps):
            raise ValueError('Renseignez les deux cadences pour corriger la dérive')
        if self.method == 'alass' and (not self.referenceTrackId or not self.referenceConfirmed or self.sourceFps or self.offsetSeconds):
            raise ValueError('Alass nécessite une référence confirmée, sans correction manuelle simultanée')
        if self.method == 'manual' and self.referenceTrackId:
            raise ValueError('La référence ne concerne que la synchronisation automatique')
        return self


def tool():
    if media_tools.is_native():
        return None
    configured = os.getenv('ANIMELAB_ALASS_PATH')
    path = configured or shutil.which('alass-cli') or shutil.which('alass')
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    return str(candidate)


def capabilities():
    path = tool()
    result = dict(manual=True, alass=False, version=None, reason='Alass 2.0.0 non installé sur le serveur')
    if not path:
        if media_tools.is_native():
            result['reason'] = 'La synchronisation automatique Android reste à valider'
        return result
    try:
        response = run_process([path, '--version'], timeout=5, cancel=lambda: False, emit=lambda event: None)
        version = (response.stdout or '').strip()
        if response.returncode == 0 and version == 'alass-cli 2.0.0':
            result.update(alass=True, version='2.0.0', reason='')
        else:
            result['reason'] = 'Version Alass non validée ; utilisez 2.0.0'
    except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
        result['reason'] = 'Alass ne peut pas être exécuté'
    return result


def timing_srt(times):
    return ('\n\n'.join(f'{i+1}\n{stamp(a, comma=True)} --> {stamp(b, comma=True)}\nCue {i+1}'
                        for i, (a, b) in enumerate(times))+'\n').encode()


def alass_times(content, count):
    """Map the generated cue markers back to their original order."""
    found = {}
    for block in re.split(r'\r?\n\s*\r?\n', content.decode('utf-8-sig')):
        if not block.strip():
            continue
        markers = re.findall(r'(?m)^Cue (\d+)\s*$', block)
        times = intervals(block.encode(), '.srt')
        if len(markers) != 1 or len(times) != 1 or int(markers[0]) in found:
            raise ProviderError('Les marqueurs de répliques corrigées sont invalides', 'subtitle_sync_invalid')
        found[int(markers[0])] = times[0]
    if set(found) != set(range(1, count+1)):
        raise ProviderError('Les répliques corrigées ne correspondent pas à l’original', 'subtitle_sync_invalid')
    return [found[index] for index in range(1, count+1)]


def replace_times(content, extension, times):
    """Only replace cue timestamps; preserve all other original text and styles."""
    text, values, index = content.decode('utf-8-sig'), iter(times), 0
    if extension == '.ass':
        fields, events, output = [], False, []
        for line in text.splitlines(keepends=True):
            if line.lstrip().startswith('['):
                events = line.strip().lower() == '[events]'
            if events and line.lower().startswith('format:'):
                fields = [part.strip().lower() for part in line.partition(':')[2].split(',')]
            if events and line.lower().startswith('dialogue:'):
                parts = line.partition(':')[2].lstrip().split(',', len(fields)-1)
                a, b = next(values)
                parts[fields.index('start')], parts[fields.index('end')] = stamp(a, ass=True), stamp(b, ass=True)
                line = 'Dialogue: '+','.join(parts).rstrip('\r\n') + ('\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else '')
                index += 1
            output.append(line)
        result = ''.join(output)
    else:
        pattern = r'(?m)^(\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3})(\s+-->\s+)(\d{1,3}:\d{2}(?::\d{2})?[,.]\d{3})'
        def substitute(match):
            nonlocal index
            a, b = next(values)
            index += 1
            return stamp(a, comma=extension == '.srt')+match[2]+stamp(b, comma=extension == '.srt')
        result = re.sub(pattern, substitute, text)
    if index != len(times):
        raise ProviderError('La synchronisation a modifié le nombre de répliques', 'subtitle_sync_invalid')
    return result.encode('utf-8')


def occupancy(times):
    result = []
    for a, b in sorted(times):
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return result


def overlap(left, right):
    left, right = occupancy(left), occupancy(right)
    i, j, intersection = 0, 0, 0
    while i < len(left) and j < len(right):
        intersection += max(0, min(left[i][1], right[j][1])-max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    union = sum(b-a for a,b in left)+sum(b-a for a,b in right)-intersection
    return intersection/union if union else 0


def correction_kind(before, after):
    """Describe timing shape, never infer that two edits have the same dialogue."""
    offsets = [a-x for (a,b),(x,y) in zip(after,before)]
    spread = max(offsets)-min(offsets)
    if spread <= .25:
        return 'offset'
    xs = [a for a,b in before]
    center, mean = statistics.mean(xs), statistics.mean(offsets)
    variance = sum((x-center)**2 for x in xs)
    slope = sum((x-center)*(y-mean) for x,y in zip(xs,offsets))/variance if variance else 0
    residual = max(abs(y-(mean+slope*(x-center))) for x,y in zip(xs,offsets))
    return 'drift' if residual <= .25 else 'nonuniform'


def correct(content, extension, request, *, reference=None, directory=None, cancel=None):
    cancel = cancel or threading.Event()
    before = intervals(content, extension)
    details = dict(method=request.method, originalCues=len(before), originalLastCue=max(b for a,b in before))
    if cancel.is_set():
        raise MediaInterrupted('Synchronisation interrompue')
    if request.method == 'manual':
        factor = request.sourceFps/request.targetFps if request.sourceFps else 1
        output = shift(content, request.offsetSeconds, extension, factor=factor)
        details.update(factor=factor, offsetSeconds=request.offsetSeconds,
                       kind='drift' if factor != 1 else 'offset', sourceFps=request.sourceFps, targetFps=request.targetFps)
    else:
        caps = capabilities()
        if not caps['alass']:
            raise ProviderError(caps['reason'], 'subtitle_sync_unavailable', 409)
        if not reference:
            raise ProviderError('Une référence locale est nécessaire', 'subtitle_sync_reference')
        ref = intervals(*reference)
        if len(ref) < 5 or len(before) < 5:
            raise ProviderError('Au moins cinq répliques sont requises pour évaluer la synchronisation automatique', 'subtitle_sync_reference')
        with tempfile.TemporaryDirectory(prefix='sync-', dir=directory) as temporary:
            folder = Path(temporary)
            source, target, refpath = folder/'input.srt', folder/'output.srt', folder/'reference.srt'
            source.write_bytes(timing_srt(before))
            refpath.write_bytes(timing_srt(ref))
            args = [tool(), str(refpath), str(source), str(target), '--split-penalty', '10']
            if not request.allowSplits:
                args.append('--no-split')
            try:
                result = run_process(args, timeout=120, cancel=cancel.is_set, emit=lambda event: None)
            except MediaInterrupted:
                raise
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                raise ProviderError('Alass interrompu ou indisponible ; l’original est conservé', 'subtitle_sync_failed', 409) from exc
            if result.returncode or not target.is_file() or target.stat().st_size > 10*1024*1024:
                raise ProviderError('Alass a échoué ; le sous-titre original est conservé', 'subtitle_sync_failed')
            after = alass_times(target.read_bytes(), len(before))
            if len(after) != len(before):
                raise ProviderError('Le nombre de répliques corrigées ne correspond pas à l’original', 'subtitle_sync_invalid')
            quality = overlap(ref, after)
            if quality < .55:
                raise ProviderError('Alignement insuffisant : référence ou montage probablement incompatible', 'subtitle_sync_incompatible', 409)
            output = replace_times(content, extension, after)
            offsets = [a-x for (a,b),(x,y) in zip(after,before)]
            details.update(version=caps['version'], overlapBefore=round(overlap(ref, before),4), overlapAfter=round(quality,4),
                medianOffsetSeconds=round(statistics.median(offsets),3), offsetSpreadSeconds=round(max(offsets)-min(offsets),3),
                kind=correction_kind(before, after), allowSplits=request.allowSplits)
    validated = parse_text(output, 'corrected'+extension)
    if cancel.is_set():
        raise MediaInterrupted('Synchronisation interrompue')
    details.update(correctedCues=validated['cues'], correctedLastCue=validated['lastCue'])
    return output, details
