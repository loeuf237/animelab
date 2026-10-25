"""Lancement de tâches asyncio de fond avec conservation d'une référence forte.

Le noyau asyncio ne garde qu'une référence faible vers les tâches : une tâche
créée via ``asyncio.create_task`` sans être stockée peut être collectée par le
ramasse-miettes avant la fin de son exécution, et ses exceptions sont perdues.
"""
import asyncio
import logging
from typing import Any, Coroutine, Optional, Set

logger = logging.getLogger("animelab.background")

_background_tasks: Set["asyncio.Task[Any]"] = set()


def _on_done(task: "asyncio.Task[Any]") -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task %r failed: %s", task.get_name(), exc, exc_info=exc)


def spawn(coro: Coroutine[Any, Any, Any], name: Optional[str] = None) -> "asyncio.Task[Any]":
    """Crée une tâche de fond dont la référence est conservée jusqu'à sa fin."""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_on_done)
    return task
