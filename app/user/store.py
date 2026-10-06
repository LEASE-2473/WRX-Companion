"""用户资料、候选与任务持久化，复用宿主SQLite事务。"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from app.chat import store
from app.providers.profiles import get_profile
from app.user.models import Profile
from app.user.prompt_files import PROMPT, LEGACY_PROMPT

KEY = 'global_user_profile'


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS user_profile_candidates(id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, action_index INTEGER NOT NULL, document TEXT NOT NULL, status TEXT NOT NULL DEFAULT \'pending\', UNIQUE(request_id,action_index))')
    db.execute('CREATE TABLE IF NOT EXISTS user_profile_jobs(date TEXT PRIMARY KEY,status TEXT NOT NULL,document TEXT NOT NULL)')


def load(db=None):
    if db is None:
        with store.database() as connection:
            return load(connection)
    row = db.execute('SELECT document FROM settings WHERE key=?', (KEY,)).fetchone()
    if row:
        value = Profile.model_validate_json(row[0])
        if value.summary_prompt == LEGACY_PROMPT:
            value = value.model_copy(update={'summary_prompt': PROMPT, 'revision': value.revision + 1})
            write(db, value)
        return value
    # 旧角色资料只作为一次迁移来源；冲突资料保留为候选，不覆盖或删除旧角色。
    characters = [json.loads(r[0]) for r in db.execute('SELECT document FROM characters ORDER BY rowid')]
    names = list(dict.fromkeys(c.get('user_name') for c in characters if c.get('user_name') and c['user_name'] != '用户'))
    personas = list(dict.fromkeys(c.get('persona') for c in characters if c.get('persona', '').strip()))
    value = Profile(name=names[0] if len(names) == 1 else '用户', core=personas[0] if len(personas) == 1 else '')
    initialize(db)
    for i, c in enumerate(characters):
        if (len(personas) > 1 and c.get('persona')) or (len(names) > 1 and c.get('user_name') != '用户'):
            entry = dict(tag='旧用户资料待确认', keywords=[], content=f"来源角色：{c.get('name')}；称呼：{c.get('user_name')}；介绍：{c.get('persona')}", at=store.utcnow().isoformat())
            db.execute('INSERT OR IGNORE INTO user_profile_candidates(request_id,action_index,document) VALUES (?,?,?)', ('legacy-profile', i, store.dumps(entry)))
    write(db, value)
    return value


def write(db, value):
    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET document=excluded.document', (KEY, value.model_dump_json()))


def save(value):
    if not value.name.strip():
        raise ValueError('称呼不能为空')
    if value.llm_profile_id:
        get_profile('llm', value.llm_profile_id)
    with store.database() as db:
        db.execute('BEGIN IMMEDIATE')
        old = load(db)
        if old.revision != value.revision:
            raise store.Conflict('画像已更新，请重新打开用户信息后保存')
        value = value.model_copy(update={'revision': old.revision + 1, 'name': value.name.strip()})
        write(db, value)
    return value


def candidates(db):
    initialize(db)
    return [dict(id=r['id'], status=r['status'], **json.loads(r['document'])) for r in db.execute("SELECT * FROM user_profile_candidates WHERE status='pending' ORDER BY id")]


def import_profile(value):
    if not value.name.strip():
        raise ValueError('称呼不能为空')
    with store.database() as db:
        db.execute('BEGIN IMMEDIATE')
        old = load(db)
        if old.revision != value.revision:
            raise store.Conflict('画像已更新，请重新打开后导入')
        db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET document=excluded.document', ('global_user_profile_import_backup', old.model_dump_json()))
        updated = old.model_copy(update={'name':value.name.strip(), 'core':value.core, 'entries':value.entries, 'revision':old.revision+1})
        write(db, updated)
    return updated


def commit_candidate(db, conv, rid, index, action, sources):
    initialize(db)
    doc = {k: action[k] for k in ('tag', 'keywords', 'content')}
    doc.update(at=store.utcnow().isoformat(), conversation_id=conv.id, character_id=conv.character_id, sources=sources)
    db.execute('INSERT OR IGNORE INTO user_profile_candidates(request_id,action_index,document) VALUES (?,?,?)', (rid, index, store.dumps(doc)))
    return {'name': 'append_profile_candidate', 'status': 'saved_candidate'}


def day_messages(db, date):
    from app.common.dialogue import plain_dialogue
    seen = set()
    result = []
    for r in db.execute('SELECT m.*,c.character_id FROM messages m JOIN conversations c ON c.id=m.conversation_id ORDER BY m.sequence'):
        doc = json.loads(r['document'])
        timestamp = doc.get('timestamp')
        if not timestamp or datetime.fromisoformat(timestamp).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() != date:
            continue
        content = plain_dialogue(doc.get('content', ''))
        key = (r['origin_id'] or r['id'], r['role'], content)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(time=timestamp, role=r['role'], content=content, character_id=r['character_id'], conversation_id=r['conversation_id']))
    return result


def snapshot():
    with store.database() as db:
        value = load(db)
        initialize(db)
        return {'profile': value, 'candidates': candidates(db), 'jobs': [dict(r, document=json.loads(r['document'])) for r in db.execute('SELECT * FROM user_profile_jobs ORDER BY date DESC LIMIT 14')]}


def dismiss(candidate_id):
    with store.database() as db:
        db.execute('BEGIN IMMEDIATE')
        initialize(db)
        changed = db.execute("UPDATE user_profile_candidates SET status='dismissed' WHERE id=? AND status='pending'", (candidate_id,)).rowcount
        if changed:
            value = load(db)
            write(db, value.model_copy(update={'revision': value.revision + 1}))
    return {'status': 'dismissed'}


def recover():
    with store.database() as db:
        initialize(db)
        db.execute("UPDATE user_profile_jobs SET status='interrupted' WHERE status='running'")
