from fastapi import APIRouter
from pydantic import ValidationError
from app.autonomy import service as autonomy
from app.common.errors import api_error

router = APIRouter(prefix='/api/autonomy')

@router.get('/settings')
def settings():
    return autonomy.public_settings()

@router.put('/settings')
def save(value: dict):
    try:
        return autonomy.save_settings(value)
    except ValidationError:
        raise api_error(ValueError('设置格式无效，请检查目的地地址、接入信息和额度范围'))
    except (ValueError, KeyError) as exc:
        raise api_error(exc)

@router.get('/skills')
def skills():
    if autonomy.FEATURE_ARCHIVED:return {'skills':[], 'archived':True}
    return {'skills': [{'name': name, 'content': (autonomy.SKILLS / name / 'SKILL.md').read_text(encoding='utf-8')} for name in autonomy.SKILL_NAMES]}

@router.post('/connection')
async def connection():
    try:
        autonomy.require_available()
    except ValueError as exc:
        raise api_error(exc)
    try:
        cfg = autonomy.settings()
        if cfg.provider == 'search':
            raise ValueError('搜索连接请使用已有联网设置；社区连接检查不会调用模型')
        results = []
        for key, (name, target) in autonomy.destinations(cfg).items():
            if target.provider != 'search':
                results.append({'id':key, 'name':name, 'public_posts':len(await autonomy.browse(target))})
        if not results:
            raise ValueError('没有配置社区')
        return {'status': 'ok', 'public_posts':sum(r['public_posts'] for r in results), 'destinations':results, 'model_called': False}
    except Exception:
        raise api_error(ValueError('社区连接检查失败，请检查实例地址、网络、代理与只读权限'))

@router.get('/{cid}/runs')
def runs(cid: str):
    try:
        return {'runs': autonomy.runs(cid)}
    except (ValueError, KeyError) as exc:
        raise api_error(exc)

@router.post('/{cid}/run')
async def run(cid: str):
    try:
        return await autonomy.run_activity(cid, manual=True)
    except (ValueError, KeyError) as exc:
        raise api_error(exc)

@router.post('/{cid}/depart', status_code=202)
async def depart(cid: str):
    try:
        return autonomy.depart(cid)
    except (ValueError, KeyError) as exc:
        raise api_error(exc)
