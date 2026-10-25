from fastapi import APIRouter
from animelab.api_contracts import ContractRoute
from animelab.services.playback_service import playback_service, PlaybackOpen, PlaybackSave, PlaybackState

router=APIRouter(route_class=ContractRoute,prefix='/api/playback')


@router.post('/session',response_model=PlaybackState)
async def open_playback(body: PlaybackOpen):
    return playback_service.open(body).model_dump()


@router.post('/checkpoint')
async def save_playback(body: PlaybackSave):
    return playback_service.save(body)
