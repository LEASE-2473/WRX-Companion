import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from . import manager

router = APIRouter()


@router.get('/api/extensions')
def listing():
    try: return {'extensions':manager.listing()}
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc


@router.post('/api/extensions/{eid}/{operation}')
async def control(eid: str, operation: str, request: Request):
    if request.headers.get('X-Extensions') != '1': raise HTTPException(403,'请从扩展管理入口操作')
    try:
        if operation == 'enable': await asyncio.to_thread(manager.set_enabled,eid,True)
        elif operation == 'disable': await asyncio.to_thread(manager.set_enabled,eid,False)
        elif operation == 'start': await asyncio.to_thread(manager.start,eid)
        elif operation == 'stop': await asyncio.to_thread(manager.stop,eid)
        else: raise ValueError('未知操作')
        return {'extensions':manager.listing()}
    except Exception as exc: raise HTTPException(400,str(exc)) from exc


@router.get('/apps/{eid}/{path:path}')
@router.post('/apps/{eid}/{path:path}')
@router.put('/apps/{eid}/{path:path}')
@router.patch('/apps/{eid}/{path:path}')
@router.delete('/apps/{eid}/{path:path}')
async def proxy(eid: str, path: str, request: Request):
    try:
        if '..' in path.split('/') or '\\' in path: raise ValueError('无效路径')
        if path in {'api/shutdown','api/invoke','api/health'}: raise ValueError('管理端点不开放网页代理')
        if request.method != 'GET' and request.headers.get('X-Extension-Panel') != '1': raise ValueError('缺少扩展面板请求标记')
        await asyncio.to_thread(manager.start,eid)
        instance = manager._instances[eid]; m = instance['manifest']
        if '/'+path == m.shutdown_path or '/'+path == m.invocation.endpoint: raise ValueError('管理端点不开放网页代理')
        body = await request.body()
        if len(body) > 1048576: raise ValueError('请求超过1 MiB')
        headers = {'X-Extension-Token':instance['token']}
        if request.headers.get('content-type'): headers['Content-Type'] = request.headers['content-type']
        async with httpx.AsyncClient(timeout=60,trust_env=False,follow_redirects=False) as client:
            response = await client.request(request.method, f'http://127.0.0.1:{m.internal_port}/{path}',
                params=request.query_params,content=body,headers=headers)
        return Response(response.content,status_code=response.status_code,headers={
            'Content-Type':response.headers.get('content-type','application/octet-stream'),
            'Cache-Control':'no-store','Content-Security-Policy':"frame-ancestors 'self'"})
    except Exception as exc: raise HTTPException(503,str(exc)) from exc
