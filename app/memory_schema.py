"""显式记忆字段、标签关系与旧 JSON 表的事务迁移。"""
import json
from uuid import uuid4

TABLES = {'diary': 'diaries', 'activity': 'ai_notes', 'event': 'shared_records', 'book': 'external_memory_chunks'}
COMMON = "memory_id TEXT PRIMARY KEY, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL, scope TEXT NOT NULL CHECK(scope IN ('character','conversation')), content TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '[]', injection_mode TEXT NOT NULL CHECK(injection_mode IN ('auto','hot','cold')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL"
SPECIAL = {
 'diary': "diary_date TEXT, timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai', entry_type TEXT NOT NULL DEFAULT 'daily_summary', title TEXT NOT NULL DEFAULT '', unresolved_hooks TEXT NOT NULL DEFAULT '[]'",
 'activity': "occurred_at TEXT, activity_id TEXT, activity_type TEXT NOT NULL DEFAULT '', activity_content TEXT NOT NULL DEFAULT '', execution_result TEXT NOT NULL DEFAULT '{}', note_status TEXT NOT NULL DEFAULT 'pending', note_error TEXT NOT NULL DEFAULT ''",
 'event': "occurred_at TEXT, event_tag_id TEXT NOT NULL REFERENCES event_tags(tag_id), record_type TEXT NOT NULL DEFAULT 'milestone', status TEXT NOT NULL DEFAULT 'unknown', due_at TEXT",
 'book': "occurred_at TEXT, title TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]'",
}

def tag(db, character_id, name):
    name = name.strip()
    if not name:
        raise ValueError('事件标签不能为空')
    row = db.execute('SELECT tag_id FROM event_tags WHERE character_id=? AND name=?', (character_id,name)).fetchone()
    if row:
        return row[0]
    tid = str(uuid4())
    db.execute('INSERT INTO event_tags VALUES (?,?,?)', (tid,character_id,name))
    return tid

def write(db, r):
    kind=r['kind']; table=TABLES[kind]; rid=r['id']
    values=dict(memory_id=rid, character_id=r['character_id'], conversation_id=r['conversation_id'], scope=r.get('scope','conversation'), content=r['content'], keywords=json.dumps(r.get('keywords',[]),ensure_ascii=False), injection_mode=r.get('injection_mode', 'hot' if r.get('pinned') else 'cold' if r.get('mode')=='cold' else 'auto'), created_at=r.get('created_at',''), updated_at=r.get('updated_at',''))
    if kind != 'diary':
        values['occurred_at'] = r.get('occurred_at')
    if kind=='diary':
        values.update(diary_date=r.get('date'),timezone=r.get('timezone','Asia/Shanghai'),entry_type=r.get('entry_type','daily_summary'),title=r.get('title',''),unresolved_hooks=json.dumps(r.get('unresolved_hooks',[]),ensure_ascii=False))
    elif kind=='activity':
        values.update(activity_id=r.get('activity_id'),activity_type=r.get('activity_type',''),activity_content=r.get('activity_content',''),execution_result=json.dumps(r.get('execution_result',{}),ensure_ascii=False),note_status=r.get('note_status','pending'),note_error=r.get('note_error',''))
    elif kind=='event':
        if len(r.get('tags',[]))!=1:
            raise ValueError('重要事件必须有且仅有一个事件标签')
        values.update(event_tag_id=tag(db,r['character_id'],r['tags'][0]),record_type=r.get('record_type','milestone'),status=r.get('status','unknown'),due_at=r.get('due_at'))
    else:
        values.update(title=r.get('title',''),tags=json.dumps(r.get('tags',[]),ensure_ascii=False));values['injection_mode']='cold'
    cols=list(values)
    db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) ON CONFLICT(memory_id) DO UPDATE SET "+','.join(f'{c}=excluded.{c}' for c in cols if c!='memory_id'), list(values.values()))
    db.execute('DELETE FROM memory_sources WHERE memory_id=?',(rid,))
    db.executemany('INSERT OR IGNORE INTO memory_sources VALUES (?,?)',[(rid,s) for s in r.get('sources',[])])
    if kind=='diary':
        db.execute('DELETE FROM diary_event_tags WHERE diary_id=?',(rid,))
        db.executemany('INSERT INTO diary_event_tags VALUES (?,?)',[(rid,tid) for tid in dict.fromkeys(tag(db,r['character_id'],t) for t in r.get('tags',[]))])
    db.execute("INSERT INTO memory_vectors VALUES (?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET vector=excluded.vector,model_signature=excluded.model_signature,index_state=excluded.index_state",(rid,json.dumps(r.get('vector')) if r.get('vector') is not None else None,r.get('vector_signature',''),'ready' if r.get('vector') else 'pending'))

def read(db,kind,row):
    r=dict(row);rid=r.pop('memory_id');r.update(id=rid,kind=kind)
    r['keywords']=json.loads(r['keywords'])
    if kind=='diary':
        r['date']=r.pop('diary_date');r['unresolved_hooks']=json.loads(r['unresolved_hooks'])
        rows=db.execute('SELECT t.tag_id,t.name FROM event_tags t JOIN diary_event_tags d ON t.tag_id=d.tag_id WHERE d.diary_id=? ORDER BY t.tag_id',(rid,)).fetchall()
        r['tag_ids']=[x[0] for x in rows];r['tags']=[x[1] for x in rows]
    elif kind=='event':
        row=db.execute('SELECT name FROM event_tags WHERE tag_id=?',(r['event_tag_id'],)).fetchone()
        r['tags']=[row[0]];r['tag_ids']=[r['event_tag_id']]
    elif kind=='activity':
        r['tags']=[];r['execution_result']=json.loads(r['execution_result'])
    else:r['tags']=json.loads(r['tags'])
    v=db.execute('SELECT vector,model_signature FROM memory_vectors WHERE memory_id=?',(rid,)).fetchone()
    r['vector']=json.loads(v[0]) if v and v[0] else None;r['vector_signature']=v[1] if v else ''
    r['sources']=[x[0] for x in db.execute('SELECT source_id FROM memory_sources WHERE memory_id=?',(rid,))]
    r['mode']='cold' if kind=='book' or (r['injection_mode']!='hot' and r['vector'] and r['injection_mode'] in ('auto','cold')) else 'hot'
    return r

def initialize(db):
    db.execute('SAVEPOINT memory_schema')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS event_tags(tag_id TEXT PRIMARY KEY,character_id TEXT NOT NULL,name TEXT NOT NULL,UNIQUE(character_id,name))')
        db.execute('CREATE TABLE IF NOT EXISTS diary_event_tags(diary_id TEXT NOT NULL REFERENCES diaries(memory_id) ON DELETE CASCADE,tag_id TEXT NOT NULL REFERENCES event_tags(tag_id),PRIMARY KEY(diary_id,tag_id))')
        # 修复早期迁移被SQLite自动改写到已删除旧表的外键；空表时
        # foreign_key_check也不会报告此类坏引用，必须检查外键定义。
        targets = {row[2] for row in db.execute('PRAGMA foreign_key_list(diary_event_tags)')}
        if 'diaries_legacy_json' in targets:
            links = db.execute('SELECT diary_id,tag_id FROM diary_event_tags').fetchall()
            db.execute('DROP TABLE diary_event_tags')
            db.execute('CREATE TABLE diary_event_tags(diary_id TEXT NOT NULL REFERENCES diaries(memory_id) ON DELETE CASCADE,tag_id TEXT NOT NULL REFERENCES event_tags(tag_id),PRIMARY KEY(diary_id,tag_id))')
            db.executemany('INSERT INTO diary_event_tags VALUES (?,?)', links)
        db.execute('CREATE TABLE IF NOT EXISTS memory_sources(memory_id TEXT NOT NULL,source_id TEXT NOT NULL,PRIMARY KEY(memory_id,source_id))')
        db.execute("CREATE TABLE IF NOT EXISTS memory_vectors(memory_id TEXT PRIMARY KEY,vector TEXT,model_signature TEXT NOT NULL,index_state TEXT NOT NULL CHECK(index_state IN ('pending','ready','error')))")
        for kind,table in TABLES.items():
            columns=[x[1] for x in db.execute(f'PRAGMA table_info({table})')]
            legacy=[]
            if kind == 'diary' and 'document' not in columns and 'occurred_at' in columns:
                db.execute('ALTER TABLE diaries DROP COLUMN occurred_at')
            if 'document' in columns:
                if kind == 'diary':
                    db.execute('DROP TABLE diary_event_tags')
                legacy=[json.loads(x[0]) for x in db.execute(f'SELECT document FROM {table}')]
                db.execute(f'ALTER TABLE {table} RENAME TO {table}_legacy_json')
            db.execute(f'CREATE TABLE IF NOT EXISTS {table}({COMMON},{SPECIAL[kind]})')
            if kind == 'diary':
                db.execute('CREATE TABLE IF NOT EXISTS diary_event_tags(diary_id TEXT NOT NULL REFERENCES diaries(memory_id) ON DELETE CASCADE,tag_id TEXT NOT NULL REFERENCES event_tags(tag_id),PRIMARY KEY(diary_id,tag_id))')
            for r in legacy:
                r['kind']=kind
                write(db,r)
            if 'document' in columns:
                db.execute(f'DROP TABLE {table}_legacy_json')
            db.execute(f'CREATE INDEX IF NOT EXISTS {table}_scope ON {table}(character_id,conversation_id)')
        db.execute('RELEASE memory_schema')
    except BaseException:
        db.execute('ROLLBACK TO memory_schema');db.execute('RELEASE memory_schema');raise
