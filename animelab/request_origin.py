"""Lightweight local-origin helpers shared across routers without heavy service imports."""
from fastapi import HTTPException, Request

from animelab.environment import getenv


def is_local(request: Request) -> bool:
    if getenv("ANIMELAB_SHARED_WORKER") == "1":
        return False
    return bool(request.client and request.client.host in ("127.0.0.1", "::1", "testclient"))


def local_only(request: Request) -> None:
    if not is_local(request):
        raise HTTPException(403, "La vérification dans le navigateur doit être ouverte depuis cette machine")
