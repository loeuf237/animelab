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
