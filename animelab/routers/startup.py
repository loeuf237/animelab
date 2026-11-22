"""First-run preferences and platform-aware startup capabilities."""
import asyncio
from pathlib import Path
import platform
import tempfile
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from animelab import __version__, platform_events
from animelab.api_contracts import ContractRoute
from animelab.config import settings, IS_ANDROID
from animelab.environment import getenv
from animelab.routers.network import is_local
from animelab.security import anonymize_path
from animelab.services import app_preferences
from animelab.services.app_updates import app_updates, current_version

router = APIRouter(route_class=ContractRoute, prefix='/api/app')


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    onboardingCompleted: bool | None = None
    theme: Literal['system', 'dark', 'light'] | None = None
    palette: Literal['classic', 'teal', 'lavender', 'ember', 'amoled'] | None = None
    checkUpdates: bool | None = None
    updateChannel: Literal['stable', 'beta'] | None = None
    lastSeenVersion: str | None = Field(default=None, max_length=64)


class Directory(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=4096)


def visible_preferences(values):
    return {key: values[key] for key in Preferences.model_fields if key in values}


@router.get('/startup')
async def startup_status(request: Request):
    native = await asyncio.to_thread(platform_events.storage_status)
    local = is_local(request)
    desktop = bool(getenv('ANIMAN_DESKTOP_PREFERENCES'))
    return {'preferences': visible_preferences(await asyncio.to_thread(app_preferences.load)),
            'currentVersion': current_version(),
            'runtime': 'android' if IS_ANDROID else 'desktop' if desktop else 'web',
            'os': 'android' if IS_ANDROID else platform.system().lower(), 'architecture': platform.machine().lower(),
            'storageEditable': local and not IS_ANDROID, 'native': native,
            'downloadDirectory': str(settings.DOWNLOAD_DIR) if local else anonymize_path(str(settings.DOWNLOAD_DIR))}


@router.patch('/preferences')
async def save_startup_preferences(body: Preferences):
    changes = body.model_dump(exclude_none=True)
    return visible_preferences(await asyncio.to_thread(app_preferences.save, changes))


@router.get('/updates')
async def check_application_updates(refresh: bool = False):
    prefs = await asyncio.to_thread(app_preferences.load)
    # A total deadline also bounds DNS and a peer which drips an endless body.
    try:
        return await asyncio.wait_for(app_updates.check(prefs['updateChannel'], refresh=refresh), timeout=12)
    except TimeoutError:
        return {'status': 'offline', 'currentVersion': current_version(),
                'channel': prefs['updateChannel'], 'release': None}


@router.post('/directory')
async def save_download_directory(body: Directory, request: Request):
    if not is_local(request) or IS_ANDROID:
        raise HTTPException(403, 'Host storage cannot be changed from this client')
    from animelab.services.download_manager import download_manager
    if any(task.status.value in ('DOWNLOADING', 'MUXING', 'RETRYING') for task in download_manager.tasks.values()):
        raise HTTPException(409, 'Pause active downloads before changing folders')
    path = Path(body.path).expanduser()
    if '\x00' in body.path or not path.is_absolute():
        raise HTTPException(400, 'Select an absolute folder path')
    def validate_and_save():
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
        resolved = str(path.resolve())
        app_preferences.save({'downloadDirectory': resolved, 'downloadDirectoryOrigin': getenv('ANIMELAB_DOWNLOAD_DIR')})
        return resolved
    try:
        directory = await asyncio.to_thread(validate_and_save)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, 'The selected folder is not writable') from exc
    settings.DOWNLOAD_DIR = download_manager.download_dir = directory
    return {'downloadDirectory': directory}
