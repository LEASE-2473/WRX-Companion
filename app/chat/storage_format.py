"""消息正文与请求实录的存储格式。"""
import json
import re
from app.common.time_format import normalize_times


def initialize_relationships(db):
    """分支只是独立会话的来源标记；删除日记不保留恢复快照。"""
    columns={r[1] for r in db.execute('PRAGMA table_info(conversations)')}
    for name in ('parent_conversation_id','branch_message_id'):
        if name not in columns: db.execute(f'ALTER TABLE conversations ADD COLUMN {name} TEXT')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_branches'").fetchone():
        db.execute('''UPDATE conversations SET
            parent_conversation_id=(SELECT parent_conversation_id FROM conversation_branches WHERE conversation_id=conversations.id),
            branch_message_id=(SELECT branch_message_id FROM conversation_branches WHERE conversation_id=conversations.id)
            WHERE id IN (SELECT conversation_id FROM conversation_branches)''')
        db.execute('DROP TABLE conversation_branches')
    db.execute('DROP TABLE IF EXISTS deleted_memories')
    db.execute('DROP TABLE IF EXISTS companion_states')


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k in ('content', 'timestamp') or (v is not None and v != '' and v != [] and v != {})}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def message_document(message):
    value = message.model_dump()
    for key in ('id', 'request_id', 'role', 'timezone', 'local_datetime', 'usage', 'images', 'image_count'):
        value.pop(key, None)
    return json.dumps(normalize_times(compact(value)), ensure_ascii=False, separators=(',', ':'))


def sanitize_images(value):
    """递归移除实录／快照中的图片字节；保留发生过图片输入的说明。"""
    if isinstance(value, str):
        if value.startswith('data:image/'):
            return '[图片引用：字节不保存在实录中]'
        return re.sub(r'data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+', '[图片引用：字节不保存在实录中]', value)
    if isinstance(value, dict):
        return {k: sanitize_images(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_images(v) for v in value]
    return value


def initialize_requests(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(requests)')}
    if 'debug' not in columns:
        db.execute('ALTER TABLE requests ADD COLUMN debug TEXT')
    if 'attempt' not in columns:
        db.execute('ALTER TABLE requests ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1')
    if 'fingerprint_version' not in columns:
        db.execute('ALTER TABLE requests ADD COLUMN fingerprint_version INTEGER NOT NULL DEFAULT 1')
    if 'debug_order' not in columns:
        db.execute('ALTER TABLE requests ADD COLUMN debug_order INTEGER')
        db.execute('''WITH ranked AS (SELECT id,row_number() OVER (
            PARTITION BY conversation_id ORDER BY COALESCE(finished_at,started_at),rowid) AS ordinal FROM requests)
            UPDATE requests SET debug_order=(SELECT ordinal FROM ranked WHERE ranked.id=requests.id)''')
    if 'execution' not in columns:
        db.execute("ALTER TABLE requests ADD COLUMN execution TEXT NOT NULL DEFAULT '{}'")
    if 'result' in columns:
        from app.chat.request_metadata import execution_metadata
        db.execute('CREATE TABLE IF NOT EXISTS memory_action_keys(request_id TEXT NOT NULL,action_index INTEGER NOT NULL,memory_id TEXT NOT NULL,PRIMARY KEY(request_id,action_index))')
        for rid,result,status,extra in db.execute('SELECT id,result,status,extra_usage FROM requests WHERE result IS NOT NULL').fetchall():
            value=json.loads(result)
            metadata=execution_metadata(value)
            if status=='error' and 'device_effect' not in metadata:
                metadata['device_effect']={'status':'legacy_unverified'}
            debug=value.get('debug')
            db.execute('UPDATE requests SET execution=?,debug=COALESCE(debug,?) WHERE id=?',
                       (json.dumps(metadata,ensure_ascii=False,separators=(',',':')),json.dumps(sanitize_images(debug),ensure_ascii=False,separators=(',',':')) if debug is not None else None,rid))
            for index,item in enumerate(value.get('skill_results',[])):
                if isinstance(item,dict) and item.get('memory_id'):
                    db.execute('INSERT OR IGNORE INTO memory_action_keys VALUES (?,?,?)',(rid,index,item['memory_id']))
        # 物理删除结果列；只提取必要关联、判定与已执行动作标记。
        for rid,execution in db.execute("SELECT id,execution FROM requests WHERE status='error'").fetchall():
            metadata=json.loads(execution)
            if not metadata.get('device_effect'):
                metadata['device_effect']={'status':'legacy_unverified'}
                db.execute('UPDATE requests SET execution=? WHERE id=?',
                           (json.dumps(metadata,ensure_ascii=False,separators=(',',':')),rid))
        db.execute('ALTER TABLE requests DROP COLUMN result')
    for rid, fingerprint in db.execute("SELECT id,fingerprint FROM requests WHERE typeof(fingerprint)='text'").fetchall():
        db.execute('UPDATE requests SET fingerprint=? WHERE id=?', (bytes.fromhex(fingerprint), rid))
