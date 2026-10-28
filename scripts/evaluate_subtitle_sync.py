"""Reproducible P9 synthetic timing benchmark; no network and no real media.

Run from the repository: ANIMELAB_ALASS_PATH=/absolute/alass-cli uv run --locked
python scripts/evaluate_subtitle_sync.py --output /tmp/subtitle-sync-proof.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from animelab.services.media_execution import run_process
from animelab.services.subtitle_sync import capabilities, overlap, timing_srt, tool
from animelab.services.subtitle_timing import intervals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    caps = capabilities()
    if not caps['alass']:
        raise SystemExit(caps['reason'])
    rng = random.Random(9321)
    times, cursor = [], 15
    for _ in range(70):
        cursor += rng.uniform(1.5, 8)
        length = rng.uniform(.7, 3.5)
        times.append((cursor, cursor + length))
        cursor += length
    cases = [
        ('offset', [(a+3.2, b+3.2) for a,b in times]),
        ('fps', [(a*23.976/25, b*23.976/25) for a,b in times]),
        ('cut', [(a+(20 if i>=35 else 0), b+(20 if i>=35 else 0)) for i,(a,b) in enumerate(times)]),
        ('incompatible', [(a*1.3+10+(i%3)*2, b*1.3+10+(i%3)*2) for i,(a,b) in enumerate(times)]),
    ]
    rows = []
    with tempfile.TemporaryDirectory(prefix='animelab-sync-eval-') as temporary:
        root = Path(temporary)
        ref, source, target = root/'ref.srt', root/'input.srt', root/'output.srt'
        ref.write_bytes(timing_srt(times))
        for name, values in cases:
            source.write_bytes(timing_srt(values))
            target.unlink(missing_ok=True)
            started = time.monotonic()
            result = run_process([tool(), str(ref), str(source), str(target), '--split-penalty', '10'],
                                 timeout=60, cancel=lambda: False, emit=lambda event: None)
            if result.returncode or not target.is_file():
                raise RuntimeError('Alass failed on synthetic corpus: '+name)
            after = intervals(target.read_bytes(), '.srt')
            def error(values):
                return round(statistics.mean(abs(a-x) for (a,b),(x,y) in zip(values,times)),6) if len(values)==len(times) else None
            score = overlap(times, after)
            rows.append(dict(case=name, cues=len(after), beforeMeanSeconds=error(values), afterMeanSeconds=error(after),
                             overlapAfter=round(score,6), accepted=score>=.55, elapsedSeconds=round(time.monotonic()-started,3)))
    report = dict(tool='alass-cli', version=caps['version'], seed=9321, cues=70, synthetic=True,
                  binarySha256=hashlib.sha256(Path(tool()).read_bytes()).hexdigest(),
                  source='https://github.com/kaegi/alass/releases/tag/v2.0.0',
                  checksumOrigin='Locally computed, not an upstream signature',
                  platform=sys.platform, splitPenalty=10, allowSplits=True, minimumOverlap=.55, cases=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
