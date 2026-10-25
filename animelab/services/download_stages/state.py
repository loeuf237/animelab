"""Legal transfer lifecycle; native export has an independent persistent state."""
from animelab.models.download_task import DownloadStatus as S

# Completion can be recovered from a verified local file without a network phase.
TRANSITIONS = {
    S.PENDING: {S.DOWNLOADING, S.PAUSED, S.CANCELLED, S.SCHEDULED, S.COMPLETED, S.FAILED, S.MUXING},
    S.SCHEDULED: {S.PENDING, S.PAUSED, S.CANCELLED},
    S.DOWNLOADING: {S.RETRYING, S.PAUSED, S.CANCELLED, S.FAILED, S.MUXING, S.COMPLETED, S.VERIFICATION_REQUIRED},
    S.RETRYING: {S.PENDING, S.DOWNLOADING, S.PAUSED, S.CANCELLED, S.FAILED, S.MUXING, S.COMPLETED, S.VERIFICATION_REQUIRED},
    S.MUXING: {S.PAUSED, S.CANCELLED, S.FAILED, S.COMPLETED},
    S.PAUSED: {S.PENDING, S.CANCELLED, S.COMPLETED, S.FAILED, S.MUXING},
    S.FAILED: {S.PENDING, S.PAUSED, S.CANCELLED, S.COMPLETED, S.MUXING},
    S.CANCELLED: {S.PENDING, S.PAUSED},
    S.COMPLETED: {S.PENDING, S.FAILED},
    S.VERIFICATION_REQUIRED: {S.PAUSED, S.PENDING, S.CANCELLED, S.FAILED},
}


def transition(task, target: S):
    if task.status != target and target not in TRANSITIONS[task.status]:
        raise ValueError(f'Invalid download transition: {task.status.value} -> {target.value}')
    task.status = target
