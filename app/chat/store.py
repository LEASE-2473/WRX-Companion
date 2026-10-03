"""事务会话存储。原始消息由服务端追加，客户端没有整段覆盖接口。"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from app.common.identity import new_id
from app.common.time_format import utc_seconds, normalize_times
from app.chat.storage_format import message_document, sanitize_images, initialize_requests, initialize_relationships
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import DATA_DIR, CONVERSATIONS_FILE
from app.models import Character, ConversationRecord, HeartbeatSettings, StoredMessage, TokenUsage

DB_PATH = DATA_DIR / "companion.sqlite3"
_initialized: set[str] = set()


class Conflict(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("无效的 IANA 时区") from exc
    return value


def dumps(value) -> str:
    return json.dumps(normalize_times(value), ensure_ascii=False, separators=(",", ":"))


@contextmanager
def database():
    path = Path(os.environ.get("WRX_DB_PATH", str(DB_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    try:
        if str(path) not in _initialized:
            _initialize(db)
            _initialized.add(str(path))
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS characters(id TEXT PRIMARY KEY, document TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id),
            name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            timezone TEXT NOT NULL, heartbeat TEXT NOT NULL, next_heartbeat_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            request_id TEXT, role TEXT NOT NULL, document TEXT NOT NULL,
            UNIQUE(conversation_id,request_id,role));
        CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,sequence);
        CREATE TABLE IF NOT EXISTS requests(
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
            fingerprint BLOB NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, error TEXT,
            usage TEXT, extra_usage TEXT);
        CREATE INDEX IF NOT EXISTS requests_conversation ON requests(conversation_id,status);
        CREATE TABLE IF NOT EXISTS regenerations(request_id TEXT PRIMARY KEY REFERENCES requests(id), message_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS resends(request_id TEXT PRIMARY KEY REFERENCES requests(id), message_id TEXT NOT NULL, content TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, document TEXT NOT NULL);
    """)
    from app.chat import images as image_store
    image_store.initialize(db)
    initialize_requests(db)
    initialize_relationships(db)
    if 'origin_id' not in {r[1] for r in db.execute('PRAGMA table_info(messages)')}:
        db.execute('ALTER TABLE messages ADD COLUMN origin_id TEXT')
        db.execute('UPDATE messages SET origin_id=id')
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    default = Character(id="default", name="温柔乡", system_prompt="你是用户的 AI 陪伴者，保持自然、连续的交流。")
    db.execute("INSERT OR IGNORE INTO characters VALUES (?,?)", (default.id, default.model_dump_json()))
    # 仅迁移一次。保持旧文件不变；损坏文件阻止迁移，不静默吞掉历史。
    if not db.execute("SELECT 1 FROM settings WHERE key='legacy_imported'").fetchone():
        if CONVERSATIONS_FILE.exists():
            raw = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("旧 conversations.json 必须为数组，请先修复或备份")
            imported_ids = {}
            for item in raw:
                now = utc_seconds(utcnow())
                old_cid = str(item["id"])
                cid = imported_ids.setdefault(old_cid,new_id(lambda value: db.execute('SELECT 1 FROM conversations WHERE id=?',(value,)).fetchone()))
                db.execute("INSERT OR IGNORE INTO conversations(id,character_id,name,created_at,updated_at,timezone,heartbeat,next_heartbeat_at) VALUES (?,?,?,?,?,?,?,NULL)",
                           (cid, "default", str(item.get("name") or "旧对话"), normalize_times(item.get("created_at") or now),
                            normalize_times(item.get("updated_at") or now), "Asia/Shanghai", HeartbeatSettings().model_dump_json()))
                for index, old in enumerate(item.get("messages", [])):
                    if old.get("role") not in {"user", "assistant"}:
                        continue
                    # 旧消息没有真实时间，明确保留为未知，不虚构精确发生时间。
                    message = StoredMessage(id=new_id(lambda value: db.execute('SELECT 1 FROM messages WHERE id=?',(value,)).fetchone()), role=old["role"], content=str(old["content"]),
                                            timestamp="", local_datetime="", source="legacy")
                    _insert_message(db, cid, message)
        db.execute("INSERT INTO settings VALUES ('legacy_imported','true')")
    db.commit()


def _character(db, cid):
    row = db.execute("SELECT document FROM characters WHERE id=?", (cid,)).fetchone()
    if not row:
        raise KeyError("角色不存在")
    return Character.model_validate_json(row[0])


def list_characters():
    with database() as db:
        return [Character.model_validate_json(row[0]) for row in db.execute("SELECT document FROM characters ORDER BY rowid")]


def get_character(cid):
    with database() as db:
        return _character(db, cid)


def save_character(value: Character):
    value = value.model_copy(deep=True)
    value.name = value.name.strip()
    if not value.name:
        raise ValueError("角色名称不能为空")
    with database() as db:
        value.id = value.id or new_id(lambda fresh: db.execute('SELECT 1 FROM characters WHERE id=?',(fresh,)).fetchone())
        db.execute("INSERT INTO characters VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                   (value.id, value.model_dump_json()))
    return value


def delete_character(cid):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        _character(db, cid)
        if cid == "default" or db.execute("SELECT 1 FROM conversations WHERE character_id=?", (cid,)).fetchone():
            raise Conflict("默认角色或已有会话的角色不能删除，可修改名称与设定")
        db.execute("DELETE FROM characters WHERE id=?", (cid,))


def _conversation(db, cid, include_messages=True):
    row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    if not row:
        raise KeyError("会话不存在")
    data = dict(row)
    data["heartbeat"] = json.loads(data["heartbeat"])
    data["messages"] = [dict(json.loads(m["document"]), id=m["id"], request_id=m["request_id"], role=m["role"], timezone=data["timezone"], local_datetime="") for m in db.execute(
        "SELECT id,origin_id,request_id,role,document FROM messages WHERE conversation_id=? ORDER BY sequence", (cid,))] if include_messages else []
    from app.chat import images as image_store
    for item in data['messages']:
        item['images'] = image_store.urls(db, item['id'])
        item['image_count'] = db.execute('SELECT count(*) FROM images WHERE message_id=?', (item['id'],)).fetchone()[0]
        item['usage'] = None
        usage_row = db.execute('SELECT r.usage FROM requests r JOIN messages m ON m.request_id=r.id WHERE m.id=?',(item['id'],)).fetchone()
        if not usage_row:
            usage_row = db.execute('SELECT r.usage FROM requests r JOIN messages m ON m.request_id=r.id WHERE m.id=(SELECT origin_id FROM messages WHERE id=?)',(item['id'],)).fetchone()
        if usage_row and usage_row[0]: item['usage'] = json.loads(usage_row[0])
    pending = db.execute("SELECT id FROM requests WHERE conversation_id=? AND status='running'", (cid,)).fetchone()
    data["pending_request_id"] = pending[0] if pending else None
    return ConversationRecord.model_validate(data)


def get_conversation(cid):
    with database() as db:
        return _conversation(db, cid)


def list_conversations(character_id=None):
    with database() as db:
        query = "SELECT id FROM conversations"
        args = ()
        if character_id:
            query += " WHERE character_id=?"
            args = (character_id,)
        query += " ORDER BY updated_at DESC"
        return [_conversation(db, row[0], False) for row in db.execute(query, args).fetchall()]


def create_conversation(character_id="default", name="", tz="Asia/Shanghai"):
    valid_timezone(tz)
    with database() as db:
        char = _character(db, character_id)
        now = utc_seconds(utcnow())
        cid = new_id(lambda value: db.execute('SELECT 1 FROM conversations WHERE id=?',(value,)).fetchone())
        db.execute("INSERT INTO conversations(id,character_id,name,created_at,updated_at,timezone,heartbeat,next_heartbeat_at) VALUES (?,?,?,?,?,?,?,NULL)",
                   (cid, character_id, name.strip() or f"{char.name} · 新对话", now, now, tz, HeartbeatSettings().model_dump_json()))
        return _conversation(db, cid)


def _insert_message(db, cid, message):
    existing = db.execute('SELECT id FROM messages WHERE conversation_id=? AND request_id=? AND role=?',(cid,message.request_id,message.role)).fetchone() if message.request_id else None
    if existing: return
    if db.execute('SELECT 1 FROM messages WHERE id=?',(message.id,)).fetchone():
        message.id = new_id(lambda fresh: db.execute('SELECT 1 FROM messages WHERE id=?',(fresh,)).fetchone())
    db.execute("INSERT INTO messages(id,conversation_id,request_id,role,document) VALUES (?,?,?,?,?)",
               (message.id, cid, message.request_id, message.role, message_document(message.model_copy(update={'images': []}))))
    db.execute('UPDATE messages SET origin_id=COALESCE(origin_id,id) WHERE id=?',(message.id,))
    if message.images:
        from app.chat import images as image_store
        if not db.execute('SELECT 1 FROM images WHERE message_id=?', (message.id,)).fetchone():
            image_store.save(db, cid, message.id, message.images, message.timestamp)


def edit_user_message(cid, mid, content):
    """只修改用户正文，保留附件、时间和后续回复，不调用模型。"""
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        conversation = _conversation(db, cid)
        if conversation.pending_request_id:
            raise Conflict("请等待当前回复完成后编辑")
        target = next((m for m in conversation.messages if m.id == mid), None)
        if target is None:
            raise KeyError("消息不存在")
        if target.role != "user":
            raise ValueError("仅支持编辑用户正文")
        if not content.strip() and not target.image_count:
            raise ValueError("消息不能为空")
        edited = target.model_copy(update={"content": content})
        db.execute("UPDATE messages SET document=? WHERE id=? AND conversation_id=?", (message_document(edited), mid, cid))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_seconds(utcnow()), cid))
        return edited


def branch_conversation(cid, mid, action="branch", content=None):
    """复制消息前缀，原会话保持不变；编辑/重生成始终产生新分支。"""
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        original = _conversation(db, cid)
        if original.pending_request_id:
            raise Conflict("请等待当前回复完成后创建分支")
        index = next((i for i, m in enumerate(original.messages) if m.id == mid), None)
        if index is None:
            raise KeyError("消息不存在")
        target = original.messages[index]
        resend = None
        edited = None
        if action == "regenerate":
            if target.role != "assistant" or index == 0 or original.messages[index - 1].role != "user" or target.source == "heartbeat":
                raise ValueError("只能重新生成用户消息后的 AI 回复")
            require_latest(original,mid,'assistant')
            index -= 1
            resend = original.messages[index].content
            prefix = original.messages[:index + 2]
        elif action == "edit":
            if not content or not content.strip():
                raise ValueError("编辑内容不能为空")
            prefix = original.messages[:index]
            if target.role == "user":
                require_latest(original,mid,'user')
                prefix = original.messages[:index + 1]
                resend = content
            else:
                edited = new_message("assistant", content, original.timezone, "edit", None)
        elif action == "branch":
            prefix = original.messages[:index + 1]
        else:
            raise ValueError("不支持的消息操作")
        now = utc_seconds(utcnow())
        branch_id = new_id(lambda value: db.execute('SELECT 1 FROM conversations WHERE id=?',(value,)).fetchone())
        stem = original.name.split(" · 分支")[0]
        names = {row[0] for row in db.execute("SELECT name FROM conversations WHERE character_id=?", (original.character_id,))}
        number = 1
        while f"{stem} · 分支 {number}" in names:
            number += 1
        db.execute("INSERT INTO conversations(id,character_id,name,created_at,updated_at,timezone,heartbeat,next_heartbeat_at) VALUES (?,?,?,?,?,?,?,NULL)",
                   (branch_id, original.character_id, f"{stem} · 分支 {number}", now, now,
                    original.timezone, HeartbeatSettings().model_dump_json()))
        db.execute("UPDATE conversations SET parent_conversation_id=?,branch_message_id=? WHERE id=?", (cid, mid, branch_id))
        copied = {}
        for message in prefix:
            copy_id = new_id(lambda value: db.execute('SELECT 1 FROM messages WHERE id=?',(value,)).fetchone())
            copied[message.id] = copy_id
            _insert_message(db, branch_id, message.model_copy(update={"id": copy_id, "request_id": None, "images": []}))
            from app.chat import images as image_store
            image_store.copy(db, message.id, copy_id, branch_id)
            db.execute('UPDATE messages SET origin_id=(SELECT COALESCE(origin_id,id) FROM messages WHERE id=?) WHERE id=?',(message.id,copy_id))
        if edited:
            _insert_message(db, branch_id, edited)
        return {"conversation": _conversation(db, branch_id), "resend_content": resend, "resend_images": [], "resend_mid": copied.get(mid) if action=="edit" and target.role=="user" else None, "regenerate_mid": copied.get(mid) if action=="regenerate" else None}


def new_message(role, content, tz, source, request_id, usage=None, sources=None, images=None):
    now = utcnow()
    return StoredMessage(id=new_id(), role=role, content=content, timestamp=utc_seconds(now), timezone=tz,
                         local_datetime="", source=source,
                         request_id=request_id, usage=usage, sources=sources or [], images=images or [])


def get_request(rid, include_debug=False):
    with database() as db:
        from app.chat.maintenance import expire_debug
        expire_debug(db, request_id=rid)
        row = db.execute("SELECT " + ("*" if include_debug else "id,conversation_id,fingerprint,source,status,started_at,finished_at,execution,error,usage,extra_usage,attempt,fingerprint_version") + " FROM requests WHERE id=?", (rid,)).fetchone()
        if not row:
            raise KeyError("请求不存在")
        data = dict(row)
        for key in ("execution", "usage", "extra_usage", "debug"):
            if key not in data: continue
            data[key] = json.loads(data[key]) if data[key] else None
        return data


def begin_turn(cid, rid, text, tz, source, search_mode, guard=None, regenerate_mid=None, images=None, resend_mid=None):
    valid_timezone(tz)
    now = utcnow()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        conversation = _conversation(db, cid)
        existing = db.execute("SELECT id,fingerprint,fingerprint_version,status,started_at,attempt FROM requests WHERE id=?", (rid,)).fetchone()
        version = existing['fingerprint_version'] if existing else 2
        payload_images = images
        if version >= 2 and (regenerate_mid or resend_mid):
            attachment_mid = resend_mid
            if regenerate_mid and not resend_mid:
                image_user = db.execute("SELECT id FROM messages WHERE conversation_id=? AND role='user' AND sequence<(SELECT sequence FROM messages WHERE id=?) ORDER BY sequence DESC LIMIT 1",(cid,regenerate_mid)).fetchone()
                attachment_mid = image_user[0] if image_user else None
            payload_images = [{'image_ref':r[0]} for r in db.execute('SELECT origin_id FROM images WHERE message_id=? ORDER BY rowid',(attachment_mid,))]
        payload = [cid,text,tz,source,search_mode] + ([regenerate_mid] if regenerate_mid else []) + ([payload_images] if payload_images else []) + (['resend',resend_mid] if resend_mid else [])
        fingerprint = hashlib.sha256(dumps(payload).encode()).digest()
        if existing:
            legacy_row = db.execute("SELECT document FROM settings WHERE key='storage_legacy_requests'").fetchone()
            if legacy_row and rid in json.loads(legacy_row[0]):
                alias_row = db.execute("SELECT document FROM settings WHERE key='storage_identity_aliases'").fetchone()
                aliases = json.loads(alias_row[0]) if alias_row else {}
                legacy_payload = [aliases.get(cid,cid),text,tz,source,search_mode]
                if regenerate_mid: legacy_payload.append(aliases.get(regenerate_mid,regenerate_mid))
                if payload_images:
                    legacy_images = [{'image_ref':aliases.get(item['image_ref'],item['image_ref'])} for item in payload_images] if version >= 2 and (regenerate_mid or resend_mid) else payload_images
                    legacy_payload.append(legacy_images)
                if resend_mid: legacy_payload += ['resend',aliases.get(resend_mid,resend_mid)]
                fingerprint = hashlib.sha256(json.dumps(legacy_payload,ensure_ascii=False,separators=(',',':')).encode()).digest()
            if existing["fingerprint"] != fingerprint:
                raise Conflict("同一 request_id 不能用于不同消息")
            if existing["status"] != "error":
                return False
        if existing and existing['status']=='error' and not regenerate_mid and not resend_mid:
            owner=next((m for m in conversation.messages if m.request_id==rid and m.role=='user'),None)
            if owner: require_latest(conversation,owner.id,'user')
        # 任务最长 180 秒。超时的旧进程请求可释放；迟到结果不得写入。
        cutoff = utc_seconds(now - timedelta(seconds=240))
        db.execute("UPDATE requests SET status='error',error='请求中断或超时',finished_at=? WHERE conversation_id=? AND status='running' AND started_at<?",
                   (utc_seconds(now), cid, cutoff))
        if db.execute("SELECT 1 FROM requests WHERE conversation_id=? AND status='running'", (cid,)).fetchone():
            raise Conflict("当前会话正在生成回复，请等本轮完成")
        if source == "heartbeat" and guard:
            reason = guard(_conversation(db, cid))
            if reason:
                raise Conflict(reason)
        if existing:
            db.execute("UPDATE requests SET status='running',started_at=?,attempt=attempt+1,finished_at=NULL,debug=NULL,error=NULL,usage=NULL,extra_usage=NULL WHERE id=?", (utc_seconds(now), rid))
        else:
            db.execute("INSERT INTO requests(id,conversation_id,fingerprint,source,status,started_at,fingerprint_version) VALUES (?,?,?,?,'running',?,2)",
                       (rid, cid, fingerprint, source, utc_seconds(now)))
        db.execute("UPDATE conversations SET timezone=?,updated_at=? WHERE id=?", (tz, utc_seconds(now), cid))
        if resend_mid:
            require_latest(conversation,resend_mid,'user')
            index = next((i for i,m in enumerate(conversation.messages) if m.id == resend_mid and m.role == 'user'), -1)
            if index < 0:
                raise ValueError('只能原地重新发送用户消息')
            following = conversation.messages[index+1:]
            if following:
                if following[0].role != 'assistant' or following[0].source == 'heartbeat':
                    raise ValueError('这条消息没有可原地替换的回复，请使用新分支')
                db.execute('INSERT OR REPLACE INTO regenerations VALUES (?,?)', (rid, following[0].id))
            db.execute('INSERT OR REPLACE INTO resends VALUES (?,?,?)', (rid, resend_mid, text))
        elif regenerate_mid:
            require_latest(conversation,regenerate_mid,'assistant')
            target = next((m for m in conversation.messages if m.id == regenerate_mid), None)
            if not target or target.role != "assistant" or target.source == "heartbeat":
                raise ValueError("该消息不支持重新生成")
            index = conversation.messages.index(target)
            if index == 0 or conversation.messages[index - 1].role != "user" or conversation.messages[index - 1].content != text:
                raise Conflict("重新生成的原始输入已变化")
            db.execute("INSERT OR REPLACE INTO regenerations VALUES (?,?)", (rid, regenerate_mid))
        elif source != "heartbeat":
            _insert_message(db, cid, new_message("user", text, tz, source, rid, images=images))
        return True


def finish_turn(rid, content, usage, extra_usage, sources, result, attempt_started_at=None):
    from app.character import state as role_state
    emotion_config = role_state.config()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id,conversation_id,source,status,started_at,attempt FROM requests WHERE id=?", (rid,)).fetchone()
        if not row or row["status"] != "running" or (attempt_started_at and (row["attempt"] if isinstance(attempt_started_at, int) else row["started_at"]) != attempt_started_at):
            raise Conflict("请求已结束，拒绝写入迟到结果")
        conversation = _conversation(db, row["conversation_id"])
        resend = db.execute('SELECT message_id,content FROM resends WHERE request_id=?', (rid,)).fetchone()
        if resend:
            if not content:
                raise ValueError('原地重新发送未返回正文，原消息保留')
            original = next(m for m in conversation.messages if m.id == resend['message_id'])
            edited = original.model_copy(update={'content':resend['content']})
            db.execute('UPDATE messages SET document=? WHERE id=? AND conversation_id=?', (message_document(edited), edited.id, conversation.id))
        result = dict(result)
        result['emotion_change'] = {'status':'disabled','changes':[]}
        if emotion_config.enabled:
            previous = role_state.calculate(db, conversation, utcnow(), emotion_config)
            updated = role_state.apply(db, conversation, result.get('emotion_updates', []), row['source'], emotion_config, result.get('emotion_revision'))
            stale = result.get('emotion_revision') is not None and previous['revision'] != result['emotion_revision']
            changes = [{'emotion':item['emotion'], 'before':previous['values'][item['emotion']], 'after':updated['values'][item['emotion']]}
                       for item in result.get('emotion_updates', []) if not stale and previous['values'][item['emotion']] != updated['values'][item['emotion']]]
            result['emotion_change'] = {'status':'invalid' if result.get('emotion_warning') else 'stale' if stale else 'changed' if changes else 'unchanged','changes':changes}
            if result.get('emotion_warning'):role_state.log(db,conversation.id,{'source':row['source'],'status':'invalid','warning':result['emotion_warning']})
        message = None
        if content:
            message = new_message("assistant", content, conversation.timezone, row["source"], rid, usage, sources)
            target = db.execute("SELECT message_id FROM regenerations WHERE request_id=?", (rid,)).fetchone()
            if target:
                message = message.model_copy(update={"id": target["message_id"]})
                changed = db.execute("UPDATE messages SET request_id=?,document=? WHERE id=? AND conversation_id=?", (rid, message_document(message), message.id, conversation.id)).rowcount
                if not changed:
                    raise Conflict("待重新生成的消息已不存在")
            else:
                _insert_message(db, conversation.id, message)
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_seconds(utcnow()), conversation.id))
        from app.skills import runtime as chat_skills
        skill_actions = result.pop('_skill_actions', [])
        skill_sources = result.pop('_skill_source_ids', [])
        skill_sources += [m.id for m in conversation.messages if m.request_id == rid]
        if message: skill_sources.append(message.id)
        regenerated = bool(db.execute('SELECT 1 FROM regenerations WHERE request_id=?', (rid,)).fetchone() or resend)
        result['skill_results'] = chat_skills.commit(db, conversation, rid, skill_actions, list(dict.fromkeys(skill_sources)), regenerated) if skill_actions else []
        if resend: db.execute("UPDATE resends SET content='' WHERE request_id=?",(rid,))
        result = {**result, "assistant_message": message.model_dump() if message else None}
        from app.chat.request_metadata import execution_metadata
        metadata=execution_metadata(result)
        previous=json.loads(db.execute('SELECT execution FROM requests WHERE id=?',(rid,)).fetchone()[0])
        if previous.get('device_effect'): metadata['device_effect']=previous['device_effect']
        debug = result.pop('debug', None)
        db.execute("UPDATE requests SET status='complete',finished_at=?,execution=?,debug=?,usage=?,extra_usage=? WHERE id=?",
                   (utc_seconds(utcnow()), dumps(metadata), dumps(sanitize_images(debug)) if debug is not None else None, usage.model_dump_json(), dumps(extra_usage), rid))
        db.execute('UPDATE requests SET debug_order=(SELECT COALESCE(MAX(debug_order),0)+1 FROM requests WHERE conversation_id=?) WHERE id=?',(conversation.id,rid))
        from app.chat.maintenance import expire_debug
        expire_debug(db)
        return result


def fail_turn(rid, error, usage=None, extra_usage=None, attempt_started_at=None, result=None):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT status,attempt,started_at FROM requests WHERE id=?',(rid,)).fetchone()
        if not row or row['status'] != 'running': return
        lease = row['attempt'] if isinstance(attempt_started_at, int) else row['started_at']
        if attempt_started_at is not None and lease != attempt_started_at: return
        value = dict(result or {})
        debug = value.pop('debug', None)
        db.execute("UPDATE requests SET status='error',finished_at=?,error=?,usage=?,extra_usage=?,debug=? WHERE id=?",
                   (utc_seconds(utcnow()),error,usage.model_dump_json() if usage else None,dumps(extra_usage or []),
                    dumps(sanitize_images(debug)) if debug is not None else None,rid))
        db.execute('UPDATE requests SET debug_order=(SELECT COALESCE(MAX(debug_order),0)+1 FROM requests WHERE conversation_id=(SELECT conversation_id FROM requests WHERE id=?)) WHERE id=?',(rid,rid))
        from app.chat.maintenance import expire_debug
        expire_debug(db)


def get_setting(key, default):
    with database() as db:
        row = db.execute("SELECT document FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default


def save_setting(key, value):
    with database() as db:
        db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET document=excluded.document", (key, dumps(value)))


def save_heartbeat(cid, value: HeartbeatSettings):
    with database() as db:
        _conversation(db, cid)
        next_at = utc_seconds(utcnow() + timedelta(minutes=value.interval_minutes)) if value.enabled else None
        db.execute("UPDATE conversations SET heartbeat=?,next_heartbeat_at=? WHERE id=?", (value.model_dump_json(), next_at, cid))
        return _conversation(db, cid)


def due_heartbeats(now=None):
    now = now or utcnow()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id,heartbeat FROM conversations WHERE next_heartbeat_at<=?", (utc_seconds(now),)).fetchall()
        ids = []
        for row in rows:
            config = HeartbeatSettings.model_validate_json(row["heartbeat"])
            next_at = utc_seconds(now + timedelta(minutes=config.interval_minutes)) if config.enabled else None
            db.execute("UPDATE conversations SET next_heartbeat_at=? WHERE id=?", (next_at, row["id"]))
            if config.enabled:
                ids.append(row["id"])
        return ids


def heartbeat_logs(cid, limit=30):
    with database() as db:
        _conversation(db, cid)
        rows=[dict(row) for row in db.execute(
            "SELECT id,status,started_at,finished_at,error,execution,usage FROM requests WHERE conversation_id=? AND source='heartbeat' ORDER BY started_at DESC,rowid DESC LIMIT ?",
            (cid, limit))]
        for row in rows:
            metadata=json.loads(row['execution'])
            message=db.execute('SELECT document FROM messages WHERE id=?',(metadata.get('reply_message_id'),)).fetchone()
            row['reply']=json.loads(message[0]).get('content','') if message else ''
        return rows


def recover_interrupted():
    # 仅回收过期请求，支持多个服务器 worker；正常任务不被其他进程启动误杀。
    with database() as db:
        cutoff = utc_seconds(utcnow() - timedelta(seconds=240))
        db.execute("UPDATE requests SET status='error',error='服务重启后回收中断请求',finished_at=? WHERE status='running' AND started_at<?",
                   (utc_seconds(utcnow()), cutoff))


def delete_conversation(cid):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        _conversation(db, cid)
        if db.execute("SELECT 1 FROM requests WHERE conversation_id=? AND status='running'", (cid,)).fetchone():
            raise Conflict("会话正在生成，请完成后删除")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity_runs'").fetchone() and db.execute("SELECT 1 FROM activity_runs WHERE conversation_id=? AND status='running' AND started_at>?", (cid, utc_seconds(utcnow() - timedelta(minutes=5)))).fetchone():
            raise Conflict('会话正在外出，请完成后删除')
        db.execute("UPDATE conversations SET parent_conversation_id=NULL,branch_message_id=NULL WHERE parent_conversation_id=?", (cid,))
        db.execute("DELETE FROM resends WHERE request_id IN (SELECT id FROM requests WHERE conversation_id=?)", (cid,))
        db.execute("DELETE FROM regenerations WHERE request_id IN (SELECT id FROM requests WHERE conversation_id=?)", (cid,))
        db.execute("DELETE FROM images WHERE conversation_id=?", (cid,))
        db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        db.execute("DELETE FROM requests WHERE conversation_id=?", (cid,))
        db.execute("DELETE FROM conversations WHERE id=?", (cid,))


def model_images(mid):
    from app.chat import images as image_store
    with database() as db:
        return image_store.urls(db, mid, model=True)


def own_images(mid):
    """仅本条消息自身附件的失败重试／最新用户重发窗口：3小时。"""
    from app.chat import images as image_store
    with database() as db:
        return image_store.urls(db,mid,model=False)


def require_latest(conversation,mid,role):
    latest=next((m for m in reversed(conversation.messages) if m.role==role),None)
    newer_user = role=='assistant' and latest and any(m.role=='user' for m in conversation.messages[conversation.messages.index(latest)+1:])
    if not latest or latest.id!=mid or newer_user:
        raise Conflict('仅最新用户消息允许重新发送' if role=='user' else '仅最新AI消息允许重新生成')


def new_request_id():
    with database() as db:
        return new_id(lambda value: db.execute('SELECT 1 FROM requests WHERE id=?',(value,)).fetchone())


def replay_request(rid):
    """从当前实体消息关联重放；实录与永久上下文快照不参与。"""
    with database() as db:
        row=db.execute('SELECT conversation_id,execution FROM requests WHERE id=?',(rid,)).fetchone()
        if not row: raise KeyError('请求不存在')
        metadata=json.loads(row['execution'])
        mid=metadata.get('reply_message_id')
        if not mid:
            found=db.execute("SELECT id FROM messages WHERE request_id=? AND role='assistant' ORDER BY sequence DESC LIMIT 1",(rid,)).fetchone()
            mid=found[0] if found else None
        conversation=_conversation(db,row['conversation_id'])
        message=next((m for m in conversation.messages if m.id==mid),None)
        return {**{k:v for k,v in metadata.items() if k not in ('reply_message_id','device_effect')},
                'reply':message.content if message else '',
                'assistant_message':message.model_dump() if message else None}


def device_effect(rid):
    with database() as db:
        row=db.execute('SELECT execution FROM requests WHERE id=?',(rid,)).fetchone()
        return (json.loads(row[0]) if row else {}).get('device_effect')


def claim_device_action(rid,name,attempt):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT status,attempt,execution FROM requests WHERE id=?',(rid,)).fetchone()
        if not row or row['status']!='running' or row['attempt']!=attempt: raise Conflict('请求已结束，拒绝设备动作')
        metadata=json.loads(row['execution'])
        if metadata.get('device_effect'): raise Conflict('本请求的设备动作已领取或执行，重试仅允许查询状态')
        metadata['device_effect']={'name':name,'status':'claimed','attempt':attempt,'at':utc_seconds(utcnow())}
        db.execute('UPDATE requests SET execution=? WHERE id=?',(dumps(metadata),rid))


def complete_device_action(rid,name):
    with database() as db:
        row=db.execute('SELECT execution FROM requests WHERE id=?',(rid,)).fetchone()
        if not row: return
        metadata=json.loads(row[0])
        if metadata.get('device_effect',{}).get('name')==name:
            metadata['device_effect']['status']='accepted'
            db.execute('UPDATE requests SET execution=? WHERE id=?',(dumps(metadata),rid))
