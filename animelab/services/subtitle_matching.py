"""Evidence-based comparison and conservative deduplication; never pick a release."""
import math
import re


def positive(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def frame_rate(value):
    try:
        numerator, denominator = str(value).split('/')
        return positive(float(numerator)/float(denominator))
    except (ValueError, ZeroDivisionError):
        return positive(value)


def compare(query, candidate, video):
    checks = []
    languages = set(query.languages.split(','))
    language = candidate['language'].lower()
    checks.append(dict(field='language', expected=query.languages, actual=language,
                       state='match' if language in languages else 'mismatch'))
    expected_fps = positive(query.expectedFps) or video.get('fps')
    actual_fps = positive(candidate.get('fps'))
    if expected_fps:
        checks.append(dict(field='fps', expected=expected_fps, actual=actual_fps,
            state='unknown' if not actual_fps else 'match' if abs(actual_fps-expected_fps) < .02 else 'mismatch'))
    expected_duration = positive(query.expectedDuration) or video.get('duration')
    actual_duration = positive(candidate.get('duration'))
    if expected_duration:
        checks.append(dict(field='duration', expected=expected_duration, actual=actual_duration,
            state='unknown' if not actual_duration else 'match' if abs(actual_duration-expected_duration) <= max(2, .02*expected_duration) else 'mismatch'))
    release = query.expectedRelease.strip()
    if release:
        tokenize = lambda text: set(re.findall(r'[a-z0-9]+', text.lower()))
        expected, actual = tokenize(release), tokenize(candidate.get('release', ''))
        score = len(expected & actual)/max(1, len(expected | actual))
        checks.append(dict(field='release', expected=release, actual=candidate.get('release'), similarity=round(score, 3),
                           state='unknown' if not actual else 'match' if score >= .8 else 'mismatch'))
    return checks


def deduplicate(results):
    """Only same provider identity or a real file digest can establish equality.

    Language, forced/HI roles and release must agree. Similar titles are never
    proof of duplicate content. Keep opaque alternatives and each provenance.
    """
    groups, ordered = {}, []
    for row in results:
        fingerprint = row.get('fingerprint')
        if isinstance(fingerprint, str) and re.fullmatch(r'[0-9a-fA-F]{32}|[0-9a-fA-F]{64}', fingerprint):
            key = ('digest', fingerprint.lower(), row['language'], row['release'], row['forced'], row['hearingImpaired'])
        else:
            key = ('identity', row['provider'], row['providerIdentity'], row['language'], row['release'], row['forced'], row['hearingImpaired'])
        if key in groups:
            groups[key]['alternatives'].append(dict(id=row['id'], provider=row['provider']))
            groups[key]['provenances'].extend(row['provenances'])
        else:
            groups[key] = row
            row['alternatives'] = [dict(id=row['id'], provider=row['provider'])]
            ordered.append(row)
    for row in ordered:
        row.pop('providerIdentity', None)
        row.pop('fingerprint', None)
    return ordered
