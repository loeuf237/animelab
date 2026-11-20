from collections import Counter
from datetime import datetime, timezone
import re
import sys
from typing import Literal
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from animelab import __version__
from animelab.api_contracts import ContractRoute
from animelab.config import IS_ANDROID
from animelab.diagnostics import read_android_crash, telemetry
from animelab.environment import getenv

router = APIRouter(route_class=ContractRoute, prefix='/api/diagnostics')
_TOKEN = re.compile(r'[^A-Za-z0-9_.:-]+')
_ERROR_EVENTS = {'server_error', 'client_error', 'update_check_failed'}


class ClientErrorReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['js_error', 'unhandled_rejection', 'vue_error', 'android_crash', 'manual']
    code: str = Field(default='unknown', max_length=80)
    component: str | None = Field(default=None, max_length=80)
    route: str | None = Field(default=None, max_length=120)


def _require_local_client(request: Request):
    if not request.client or request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Diagnostics are available on the server device only')


@router.post('/report')
async def report_client_error(request: Request, body: ClientErrorReport):
    _require_local_client(request)
    code = _TOKEN.sub('_', body.code.strip())[:80] or 'unknown'
    component = _TOKEN.sub('_', body.component.strip())[:80] if body.component else None
    telemetry.event(
        'client_error',
        errorType=body.kind,
        code=code,
        operation=component,
        route=body.route,
    )
    return {'recorded': True}


@router.get('/export')
async def export_diagnostics(request: Request):
    _require_local_client(request)
    from animelab.services.download_manager import download_manager
    events = telemetry.snapshot()
    recent_errors = sum(1 for row in events if row.get('event') in _ERROR_EVENTS)
    data_dir = getenv('ANIMAN_DATA_DIR')
    if not data_dir and IS_ANDROID:
        from animelab.config import APP_STORAGE_DIR
        data_dir = str(APP_STORAGE_DIR)
    last_crash = read_android_crash(data_dir)
    # No raw task.to_dict(), URLs, headers, recipes or database files.
    report = {
        'schemaVersion': 1,
        'applicationVersion': __version__,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'platform': sys.platform,
        'taskCounts': dict(Counter(task.status.value for task in download_manager.tasks.values())),
        'recentErrorCount': recent_errors,
        'lastCrash': last_crash,
        'events': events,
    }
    return JSONResponse(
        report,
        headers={
            'Content-Disposition': 'attachment; filename="animelab-diagnostics.json"',
            'Cache-Control': 'no-store',
        },
    )
