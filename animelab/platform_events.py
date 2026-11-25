"""Optional native lifecycle hooks. No platform imports in the shared engine."""
progress_handler = None
completed_handler = None
storage_status_handler = None
storage_action_handler = None
app_update_install_handler = None
app_update_status_handler = None
app_update_confirm_handler = None
exported_copy_exists_handler = None
exported_copy_size_handler = None
read_exported_copy_handler = None
delete_exported_copy_handler = None


def progress(task):
    if progress_handler:
        progress_handler(task)


def completed(task):
    if completed_handler:
        return completed_handler(task)


def storage_status():
    return storage_status_handler() if storage_status_handler else None


def install_app_update(path):
    return app_update_install_handler(path) if app_update_install_handler else None


def app_update_status(operation_id: str):
    return app_update_status_handler(operation_id) if app_update_status_handler and operation_id else None


def confirm_app_update(operation_id: str | None, path: str | None):
    if app_update_confirm_handler:
        return app_update_confirm_handler(operation_id or "", path or "")
    if app_update_install_handler and path:
        return app_update_install_handler(path)
    return None


def exported_copy_exists(uri: str) -> bool | None:
    return bool(exported_copy_exists_handler(uri)) if exported_copy_exists_handler else None


def exported_copy_size(uri: str) -> int | None:
    if not exported_copy_size_handler:
        return None
    size = int(exported_copy_size_handler(uri))
    return size if size >= 0 else None


def read_exported_copy(uri: str, offset: int, length: int) -> bytes:
    if not read_exported_copy_handler or offset < 0 or length <= 0:
        return b""
    return bytes(read_exported_copy_handler(uri, offset, length))


def delete_exported_copy(uri: str) -> bool:
    if not delete_exported_copy_handler or not uri:
        return False
    return bool(delete_exported_copy_handler(uri))


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
