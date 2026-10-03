import json
from fastapi import APIRouter
from app.character import state as emotion
from app.chat import store
from app.common.errors import api_error
from app.providers.profiles import get_profile

router=APIRouter(prefix='/api/role-state')

@router.get('/settings')
def settings():return emotion.config()

@router.put('/settings')
def save_settings(value:emotion.EmotionSettings):
    try:
        for pid in [value.llm_profile_id,value.contact_llm_profile_id]:
            if pid and get_profile('llm',pid).purpose != 'chat':raise ValueError('情绪管家与主动联系必须选择对话用途 Profile')
        emotion.prompt_files.write('emotion_summary',value.summary_prompt)
        store.save_setting('role_emotion_settings',value.model_dump(exclude={'summary_prompt'}));return value
    except (KeyError,ValueError) as exc:raise api_error(exc)

@router.get('/{cid}')
def state(cid:str):
    try:
        value=emotion.state(cid)
        with store.database() as db:
            logs=[json.loads(r[0]) for r in db.execute('SELECT document FROM emotion_logs WHERE conversation_id=? ORDER BY id DESC LIMIT 30',(cid,))]
            jobs=[dict(r) for r in db.execute('SELECT epoch,status,document FROM emotion_summaries WHERE conversation_id=? ORDER BY rowid DESC LIMIT 10',(cid,))]
        return {'state':value,'labels':emotion.LABELS,'groups':emotion.GROUPS,'logs':logs,'summaries':jobs}
    except (KeyError,ValueError) as exc:raise api_error(exc)

@router.patch('/{cid}')
def change(cid:str,value:dict):
    try:
        updates=emotion.validate_updates(value.get('updates',[]));cfg=emotion.config()
        with store.database() as db:
            db.execute('BEGIN IMMEDIATE');result=emotion.apply(db,store._conversation(db,cid),updates,'user',cfg)
        return result
    except (KeyError,ValueError,TypeError,AttributeError) as exc:raise api_error(ValueError(str(exc)))

@router.get('/{cid}/latest-change')
def latest_change(cid:str):
    try:
        store.get_conversation(cid)
        with store.database() as db:
            row=db.execute("SELECT id,source,finished_at,execution FROM requests WHERE conversation_id=? AND status='complete' AND (source!='heartbeat' OR json_extract(execution,'$.action')='SEND_MESSAGE') ORDER BY finished_at DESC,rowid DESC LIMIT 1",(cid,)).fetchone()
        if not row:return {'change':None}
        result=json.loads(row['execution'])
        change=result.get('emotion_change')
        if change is None:return {'change':None}
        return {'change':{**change,'request_id':row['id'],'source':row['source'],'at':row['finished_at']}}
    except (KeyError,ValueError) as exc:raise api_error(exc)

@router.post('/{cid}/summarize')
async def summarize(cid:str):
    try:return await emotion.summarize(cid)
    except (KeyError,ValueError) as exc:raise api_error(exc)

@router.post('/{cid}/assess')
async def assess(cid:str):
    try:return await emotion.assess(cid)
    except (KeyError,ValueError) as exc:raise api_error(exc)
