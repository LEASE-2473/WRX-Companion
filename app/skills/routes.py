from fastapi import APIRouter,HTTPException,Request
from app.skills import runtime as chat_skills
router=APIRouter(prefix='/api/skills')
@router.get('')
def catalog():return {'skills':chat_skills.catalog()}
@router.get('/{name}')
def read(name:str):
    try:return {'name':name,'content':chat_skills.read_skill(name)}
    except ValueError as exc:raise HTTPException(status_code=404,detail=str(exc))

@router.get('/manage/list')
def management():return {'skills':chat_skills.catalog(include_disabled=True)}

@router.put('/{name}/settings')
def configure(name: str, value: dict, request: Request):
    if request.headers.get('X-Extensions') != '1':raise HTTPException(403,'请从技能管理入口操作')
    if name not in {i['name'] for i in chat_skills.catalog(include_disabled=True)}:raise HTTPException(404,'技能不存在')
    from app.skills.configuration import save
    try:
        save(name,value)
        return {'skills':chat_skills.catalog(include_disabled=True)}
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
