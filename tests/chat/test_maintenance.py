import json
import sqlite3
from datetime import datetime, timedelta, timezone

from app.chat.maintenance import clean_database, expire_debug


def database():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,conversation_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,result TEXT,debug TEXT,debug_order INTEGER)')
    return db


def test_debug_count_boundary_and_running_requests():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    db = database()
    for cid in ('a','b'):
        for index in range(25):
            at = (now + timedelta(seconds=index)).isoformat()
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?)',
                       (cid+str(index),cid,'complete',at,at,'{"reply":"原文"}','{"llm_messages":["prompt"]}',index))
    db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?)',('running','a','running','2020-01-01T00:00:00Z',None,'{}','{"active":true}',None))
    assert expire_debug(db,now)==10
    assert db.execute("SELECT count(*) FROM requests WHERE debug IS NOT NULL AND status!='running'").fetchone()[0]==40
    assert db.execute("SELECT debug FROM requests WHERE id='running'").fetchone()[0]=='{"active":true}'
    assert db.execute("SELECT result FROM requests WHERE id='a0'").fetchone()[0]=='{"reply":"原文"}'
    assert expire_debug(db,now)==0


def test_emotion_logs_bounded_per_conversation_without_removing_summaries():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    db = database()
    db.execute('CREATE TABLE emotion_logs(id INTEGER PRIMARY KEY,conversation_id TEXT,document TEXT)')
    db.execute('CREATE TABLE emotion_summaries(document TEXT)')
    db.execute("INSERT INTO emotion_summaries VALUES ('keep')")
    for cid in ('a', 'b'):
        for index in range(205):
            at = now-timedelta(days=8) if index == 204 else now
            db.execute('INSERT INTO emotion_logs(conversation_id,document) VALUES (?,?)',
                       (cid, json.dumps({'at': at.isoformat()})))
    assert clean_database(db, now)['removed_emotion_logs'] == 12
    assert db.execute('SELECT count(*) FROM emotion_logs').fetchone()[0] == 398
    assert db.execute('SELECT document FROM emotion_summaries').fetchone()[0] == 'keep'
