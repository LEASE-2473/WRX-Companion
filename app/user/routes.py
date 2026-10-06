"""全局用户资料HTTP入口，业务与持久化交给用户模块。"""
from fastapi import APIRouter
from app.common.errors import api_error
from app.user.models import Profile, ProfileImport
from app.user import store, service

router = APIRouter(prefix='/api/user-profile')

@router.post('/import')
def import_profile(value: ProfileImport):
    try:
        return store.import_profile(value)
    except (ValueError, KeyError) as exc:
        raise api_error(exc)

@router.get('')
def read_profile():
    return store.snapshot()

@router.put('')
def update_profile(value: Profile):
    try:
        return store.save(value)
    except (ValueError, KeyError) as exc:
        raise api_error(exc)

@router.delete('/candidates/{candidate_id}')
def dismiss_candidate(candidate_id: int):
    return store.dismiss(candidate_id)

@router.post('/summarize/{date}')
async def manual_summary(date: str):
    try:
        return await service.summarize(date)
    except ValueError as exc:
        raise api_error(exc)
