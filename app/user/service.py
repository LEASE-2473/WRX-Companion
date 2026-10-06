"""每日用户画像整理与调度，模型调用位于后台。"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.chat import store
from app.models import ChatMessage
from app.providers.client import OpenAICompatibleLlm
from app.providers.profiles import resolve_llm
from app.user.models import Entry, Profile
from app.user.store import load, write, initialize, candidates, day_messages

async def summarize(date):
    datetime.strptime(date, '%Y-%m-%d')
    with store.database() as db:
        db.execute('BEGIN IMMEDIATE')
        value = load(db)
        initialize(db)
        pending = candidates(db)
        messages = day_messages(db, date)
        if not messages and not pending:
            return {'status': 'empty'}
        job = db.execute('SELECT status FROM user_profile_jobs WHERE date=?', (date,)).fetchone()
        if job and job[0] in ('running', 'done'):
            return {'status': 'already_processed'}
        db.execute('INSERT INTO user_profile_jobs VALUES (?,?,?) ON CONFLICT(date) DO UPDATE SET status=excluded.status,document=excluded.document', (date, 'running', '{}'))
    try:
        llm = OpenAICompatibleLlm(resolve_llm(profile_id=value.llm_profile_id))
        payload = {'date': date, 'profile': value.model_dump(), 'candidates': pending, 'messages': messages}
        async with asyncio.timeout(180):
            raw = await llm.complete([ChatMessage(role='system', content=value.summary_prompt), ChatMessage(role='user', content=store.dumps(payload))])
        match = re.fullmatch(r'\s*<user_profile>\s*(.*?)\s*</user_profile>\s*', raw, re.S)
        if not match:
            raise ValueError('画像总结 XML 格式无效')
        output = json.loads(match[1])
        if set(output) != {'entries'} or not isinstance(output['entries'], list):
            raise ValueError('画像总结只能返回 entries')
        updated = value.model_copy(update={'entries': [Entry.model_validate(e) for e in output['entries']], 'revision': value.revision + 1})
        updated = Profile.model_validate(updated.model_dump())
        with store.database() as db:
            db.execute('BEGIN IMMEDIATE')
            status = 'done' if load(db).revision == value.revision else 'stale'
            if status == 'done':
                write(db, updated)
                for candidate in pending:
                    db.execute("UPDATE user_profile_candidates SET status='reviewed' WHERE id=?", (candidate['id'],))
            db.execute('UPDATE user_profile_jobs SET status=?,document=? WHERE date=?', (status, store.dumps({'usage': llm.last_usage.model_dump(), 'at': store.utcnow().isoformat()}), date))
        return {'status': status}
    except BaseException as exc:
        with store.database() as db:
            db.execute('UPDATE user_profile_jobs SET status=?,document=? WHERE date=?', ('interrupted' if isinstance(exc, asyncio.CancelledError) else 'error', store.dumps({'error': '总结失败，正式画像保持原样；请检查模型配置和输出格式'}), date))
        if isinstance(exc, asyncio.CancelledError):
            raise
        return {'status': 'error'}


async def scheduler():
    while True:
        try:
            value = load()
            now = store.utcnow().astimezone(ZoneInfo('Asia/Shanghai'))
            date = (now.date() - timedelta(days=1)).isoformat()
            if value.summary_enabled and now.hour >= value.summary_hour:
                with store.database() as db:
                    initialize(db)
                    attempted = db.execute('SELECT 1 FROM user_profile_jobs WHERE date=?', (date,)).fetchone()
                if not attempted:
                    await summarize(date)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('用户画像调度失败')
        await asyncio.sleep(60)
