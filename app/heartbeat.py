"""后端生命周期内运行；调度领取与下一次时间存储在 SQLite。"""
import asyncio
import logging
from . import companion_store as store
from .companion_core import core


async def tick():
    store.recover_interrupted()
    for cid in store.due_heartbeats():
        try:
            core.heartbeat(cid)
        except (ValueError, KeyError):
            logging.warning("Heartbeat 未能启动：会话 %s，请检查角色与 LLM 配置", cid)


async def run_scheduler():
    while True:
        try:
            await tick()
        except Exception as exc:
            logging.error("Heartbeat 调度暂时失败，将重试：%s", type(exc).__name__)
        await asyncio.sleep(5)
