import asyncio
import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.chat import store
from app.tools.toy import controller as tools

router = APIRouter(prefix='/api/role-tools')

@router.get('/status/{cid}')
async def status(cid: str):
    try:
        store.get_conversation(cid)
        if tools._enabled:
            await asyncio.to_thread(tools.refresh)
        return {'tools':[tools.status(cid)]}
    except KeyError as exc:
        raise HTTPException(404, '会话不存在') from exc

@router.post('/toy/start/{cid}')
async def start(cid: str, request: Request):
    try:
        if request.headers.get('X-Role-Tools') != '1':
            raise ValueError('请从角色工具入口打开')
        store.get_conversation(cid)
        return await asyncio.to_thread(tools.start, cid)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post('/toy/close/{cid}')
async def close(cid: str, request: Request):
    try:
        if request.headers.get('X-Role-Tools') != '1':
            raise ValueError('请从角色工具入口关闭')
        store.get_conversation(cid)
        return await asyncio.to_thread(tools.close, cid)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/toy/panel')
async def panel(cid: str):
    try:
        store.get_conversation(cid)
        if not tools._enabled:
            raise ValueError('请先从角色工具中打开玩具控制')
        lease = tools._lease
        html, token = await asyncio.to_thread(tools.page)
        if not tools._enabled or tools._lease != lease:
            raise ValueError('工具连接已变更，请重新打开面板')
        html = html.replace("const token='" + token + "'", "const token='" + tools._panel_token + "'")
        html = html.replace("fetch('/api/'+command", "fetch('/api/role-tools/toy/ble/api/'+command")
        return HTMLResponse(html, headers={'Cache-Control':'no-store', 'Content-Security-Policy':"frame-ancestors 'self'"})
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc

@router.post('/toy/ble/api/{action}')
async def bridge(action: str, data: dict, request: Request):
    try:
        if action not in tools.PANEL_ACTIONS:
            raise ValueError('未知玩具操作')
        token = request.headers.get('X-BLE-Token', '')
        if not secrets.compare_digest(token, tools._panel_token):
            raise ValueError('控制面板已失效，请重新打开')
        if not tools._enabled:
            raise ValueError('工具尚未全局接入')
        return await asyncio.to_thread(tools.panel_request, token, action, data)
    except Exception as exc:
        return JSONResponse({'error':str(exc)}, status_code=400)
