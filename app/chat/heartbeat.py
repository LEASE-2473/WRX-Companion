"""后端生命周期内运行；调度领取与下一次时间存储在 SQLite。"""
import asyncio
import logging
from datetime import datetime
from app.chat import store
from app.chat.core import core


async def tick():
    store.recover_interrupted()
    from app.character import state as role_state
    await role_state.tick_summaries()
    for cid in store.due_heartbeats():
        try:
            cfg = role_state.config()
            last = store.heartbeat_logs(cid, 1)
            recent = last and (store.utcnow() - datetime.fromisoformat(last[0]['started_at'])).total_seconds() < cfg.no_action_minutes * 60
            if not recent:
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
