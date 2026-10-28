"""Optional native lifecycle hooks. No platform imports in the shared engine."""
progress_handler = None
completed_handler = None
storage_status_handler = None
storage_action_handler = None


def progress(task):
    if progress_handler:
        progress_handler(task)


def completed(task):
    if completed_handler:
        return completed_handler(task)


def storage_status():
    return storage_status_handler() if storage_status_handler else None


def completed_paths(task):
    import json
    from animelab.services.subtitle_service import normalize_subtitles
    state = json.loads(task.mediaJson).get('outputState', {})
    if json.loads(task.outputProfileJson).get('strict') and state.get('completed'):
        return [task.savePath, *state.get('sidecars', [])]
    paths = [task.savePath]
    tracks = normalize_subtitles(task.subtitlesJson)
    paths.extend(track['path'] for track in tracks if not track.get('muxed') and track.get('path'))
    if task.savePathSubtitle and not any(track.get('muxed') for track in tracks):
        try:
            sidecars = json.loads(task.savePathSubtitle)
        except ValueError:
            sidecars = task.savePathSubtitle
        paths.extend(sidecars if isinstance(sidecars, list) else [sidecars])
    return list(dict.fromkeys(path for path in paths if path))
