from fastapi import APIRouter,HTTPException
from . import chat_skills
router=APIRouter(prefix='/api/skills')
@router.get('')
def catalog():return {'skills':chat_skills.catalog()}
@router.get('/{name}')
def read(name:str):
    try:return {'name':name,'content':chat_skills.read_skill(name)}
    except ValueError as exc:raise HTTPException(status_code=404,detail=str(exc))
