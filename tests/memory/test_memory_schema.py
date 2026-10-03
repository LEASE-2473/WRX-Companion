import json
import sqlite3
import pytest
from app.memory import schema

def database():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def old_record(kind, rid, tags):
    return dict(id=rid,kind=kind,character_id='char',conversation_id='conv',content='旧正文',tags=tags,occurred_at='2026-10-01T12:00:00+08:00',date='2026-10-01',scope='character',mode='hot',pinned=True,sources=['message-1'],vector=[1,0],vector_signature='model',created_at='2026-10-01',updated_at='2026-10-01')

def legacy(db,table,r):
    db.execute(f'CREATE TABLE {table}(id TEXT PRIMARY KEY,character_id TEXT,conversation_id TEXT,document TEXT)')
    db.execute(f'INSERT INTO {table} VALUES (?,?,?,?)',(r['id'],'char','conv',json.dumps(r)))

@pytest.mark.parametrize('with_links', [False, True])
def test_repairs_stale_diary_foreign_key_and_preserves_links(with_links):
    db=database();schema.initialize(db)
    schema.write(db,old_record('diary','d',['旅行']))
    links=db.execute('SELECT * FROM diary_event_tags').fetchall() if with_links else []
    db.commit();db.execute('PRAGMA foreign_keys=OFF')
    db.execute('DROP TABLE diary_event_tags')
    db.execute('CREATE TABLE diary_event_tags(diary_id TEXT NOT NULL REFERENCES diaries_legacy_json(memory_id) ON DELETE CASCADE,tag_id TEXT NOT NULL REFERENCES event_tags(tag_id),PRIMARY KEY(diary_id,tag_id))')
    db.executemany('INSERT INTO diary_event_tags VALUES (?,?)',links)
    db.commit();db.execute('PRAGMA foreign_keys=ON')
    schema.initialize(db);schema.initialize(db)
    assert {r[2] for r in db.execute('PRAGMA foreign_key_list(diary_event_tags)')}=={'diaries','event_tags'}
    assert db.execute('SELECT * FROM diary_event_tags').fetchall()==links
    schema.write(db,old_record('diary','new',['旅行']))
    assert db.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_migration_and_stable_tag_links():
    db=database()
    legacy(db,'diaries',old_record('diary','d',['旅行','朋友']))
    legacy(db,'shared_records',old_record('event','e',['旅行']))
    schema.initialize(db);schema.initialize(db)
    d=schema.read(db,'diary',db.execute('SELECT * FROM diaries').fetchone())
    e=schema.read(db,'event',db.execute('SELECT * FROM shared_records').fetchone())
    assert d['content']=='旧正文' and d['vector']==[1,0] and d['sources']==['message-1']
    assert d['injection_mode']=='hot' and e['event_tag_id'] in d['tag_ids']
    assert 'document' not in [r[1] for r in db.execute('PRAGMA table_info(diaries)')]
    db.execute('UPDATE event_tags SET name=? WHERE tag_id=?',('旅行改名',e['event_tag_id']))
    assert '旅行改名' in schema.read(db,'diary',db.execute('SELECT * FROM diaries').fetchone())['tags']
    assert db.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_failed_migration_rolls_back_original_tables():
    db=database();legacy(db,'diaries',old_record('diary','d',['旅行']))
    legacy(db,'shared_records',old_record('event','e',[]))
    with pytest.raises(ValueError):schema.initialize(db)
    assert db.execute('SELECT document FROM diaries').fetchone()
    assert db.execute('SELECT document FROM shared_records').fetchone()
    assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE '%legacy_json'").fetchall()


def test_drop_redundant_diary_time_preserves_relations():
    db=database();schema.initialize(db)
    schema.write(db,old_record('diary','d',['旅行']))
    db.execute('ALTER TABLE diaries ADD COLUMN occurred_at TEXT')
    db.execute("UPDATE diaries SET occurred_at='2026-10-01T12:00:00+08:00'")
    schema.initialize(db)
    assert 'occurred_at' not in [r[1] for r in db.execute('PRAGMA table_info(diaries)')]
    r=schema.read(db,'diary',db.execute('SELECT * FROM diaries').fetchone())
    assert r['date']=='2026-10-01' and r['tags']==['旅行'] and r['sources']==['message-1']
    assert r['vector']==[1,0] and db.execute('PRAGMA foreign_key_check').fetchall()==[]
