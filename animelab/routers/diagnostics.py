from collections import Counter
from datetime import datetime,timezone
import sys
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import JSONResponse
from animelab import __version__
from animelab.api_contracts import ContractRoute
from animelab.diagnostics import telemetry

router=APIRouter(route_class=ContractRoute,prefix='/api/diagnostics')


@router.get('/export')
async def export_diagnostics(request: Request):
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Diagnostics are available on the server device only')
    from animelab.services.download_manager import download_manager
    # No raw task.to_dict(), settings, URLs, headers, recipes or database files.
    report={'schemaVersion':1,'applicationVersion':__version__,
            'generatedAt':datetime.now(timezone.utc).isoformat(),'platform':sys.platform,
            'taskCounts':dict(Counter(task.status.value for task in download_manager.tasks.values())),
            'events':telemetry.snapshot()}
    return JSONResponse(report,headers={'Content-Disposition':'attachment; filename="animelab-diagnostics.json"','Cache-Control':'no-store'})
