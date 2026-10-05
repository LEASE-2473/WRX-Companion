"""旧角色工具接口兼容；生命周期由通用扩展管理器负责。"""
import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.extensions import manager
router = APIRouter(prefix='/api/role-tools')
@router.get('/status/{cid}')
def status(cid: str):return {'tools':manager.listing()}
@router.post('/toy/start/{cid}')
async def start(cid: str, request: Request):
    if request.headers.get('X-Role-Tools') != '1':raise HTTPException(403,'请从工具入口操作')
    try:
        await asyncio.to_thread(manager.set_enabled,'toy',True)
        await asyncio.to_thread(manager.start,'toy')
        return {'id':'toy','running':manager.running('toy')}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@router.post('/toy/close/{cid}')
async def close(cid: str, request: Request):
    if request.headers.get('X-Role-Tools') != '1':raise HTTPException(403,'请从工具入口操作')
    try:
        await asyncio.to_thread(manager.stop,'toy')
        return {'id':'toy','running':False}
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@router.get('/toy/panel')
def panel():return RedirectResponse('/apps/toy/')
