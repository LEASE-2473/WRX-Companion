"""清理重复请求实录与诊断日志，不删除聊天正文或请求去重记录。"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

DEBUG_RETENTION_COUNT = 20
EMOTION_LOG_DAYS = 7
EMOTION_LOG_LIMIT = 200


def expire_debug(db, now=None, request_id=None):
    query = """UPDATE requests SET debug=NULL WHERE id IN (
        SELECT id FROM (SELECT id,status,row_number() OVER (
            PARTITION BY conversation_id ORDER BY debug_order DESC,started_at DESC,rowid DESC) AS position
            FROM requests WHERE debug IS NOT NULL AND status != 'running') WHERE position > 20)"""
    return db.execute(query).rowcount



def clean_database(db, now=None):
    now = now or datetime.now(timezone.utc)
    expired = expire_debug(db, now)
    removed = 0
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='emotion_logs'").fetchone():
        cutoff = (now - timedelta(days=EMOTION_LOG_DAYS)).isoformat()
        removed = db.execute("""DELETE FROM emotion_logs WHERE id IN (
            SELECT id FROM (
                SELECT id, document, row_number() OVER (
                    PARTITION BY conversation_id ORDER BY id DESC) AS position
                FROM emotion_logs
            ) WHERE position > ? OR CASE WHEN json_valid(document)
                THEN julianday(json_extract(document,'$.at')) <= julianday(?) ELSE 0 END
        )""", (EMOTION_LOG_LIMIT, cutoff)).rowcount
    from app.chat.images import cleanup
    images_removed = cleanup(db, now) if db.execute("SELECT 1 FROM sqlite_master WHERE name='images'").fetchone() else 0
    return {'expired_request_debug': expired, 'removed_emotion_logs': removed, 'expired_images': images_removed}


def maintenance_once():
    from app.chat import store
    with store.database() as db:
        return clean_database(db)


async def run_scheduler():
    while True:
        try:
            counts = await asyncio.to_thread(maintenance_once)
            if any(counts.values()):
                logging.getLogger(__name__).info('数据库清理：%s', counts)
        except Exception:
            logging.getLogger(__name__).exception('数据库清理失败，下轮重试')
        await asyncio.sleep(60)
