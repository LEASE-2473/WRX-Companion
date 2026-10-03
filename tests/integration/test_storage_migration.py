import json
import hashlib
import sqlite3
from datetime import timedelta
from pathlib import Path
import pytest
from app.chat import store
from app.common.identity import valid_id
from app.memory import role
from app.models import Character,TokenUsage
from scripts.compact_deployment_data import prepare
from tests.chat.test_images import PNG


def test_offline_compaction_references_profiles_vectors_and_replay(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir()
    monkeypatch.setenv('WRX_DB_PATH',str(source/'companion.sqlite3'))
    old_character='11111111-1111-4111-8111-111111111111'
    store.save_character(Character(id=old_character,name='迁移测试',llm_profile_id='legacy-profile'))
    conv=store.create_conversation(old_character)
    store.begin_turn(conv.id,'legacy-request','保留正文',conv.timezone,'web','OFF',images=[PNG])
    store.finish_turn('legacy-request','保留回复',TokenUsage(input_tokens=42),[],[],{'debug':{'image':PNG}})
    memory=role.put('diary',old_character,conv.id,{'content':'日记正文','date':'2026-10-03','tags':['标签']},sources=[store.get_conversation(conv.id).messages[0].id])
    with store.database() as db:
        db.execute("UPDATE memory_vectors SET vector='[0.25,0.5]',model_signature=? WHERE memory_id=?",('a'*64,memory['id']))
        db.execute('CREATE TABLE IF NOT EXISTS deleted_memories(memory_id TEXT PRIMARY KEY,deleted_at TEXT NOT NULL,document TEXT NOT NULL)')
        db.execute('INSERT INTO deleted_memories VALUES (?,?,?)',('deleted-old',store.utcnow().isoformat(),store.dumps(dict(memory,id='deleted-old'))))
        before_sequences=[tuple(r) for r in db.execute('SELECT * FROM sqlite_sequence')]
        old_fingerprint=db.execute('SELECT fingerprint FROM requests').fetchone()[0]
    profile={'llm_profiles':[{'id':'legacy-profile','name':'测试','api_key':'test-secret'}],'active_llm_profile_id':'legacy-profile'}
    (source/'provider_profiles.json').write_text(json.dumps(profile),encoding='utf-8')
    originals={p.name:p.read_bytes() for p in source.iterdir() if p.is_file()}
    output=tmp_path/'ready'/'data'
    report=prepare(source,output,store.utcnow()+timedelta(hours=4))
    assert report['source_unchanged'] and report['integrity_check']=='ok' and report['foreign_key_check']=='ok'
    assert all((source/name).read_bytes()==value for name,value in originals.items())
    assert not (output/'companion.sqlite3-wal').exists() and not (output/'companion.sqlite3-shm').exists()
    mapping=json.loads((output.parent/'data-identity-map.json').read_text(encoding='utf-8'))
    assert all(valid_id(value) for value in mapping.values())
    profiles=json.loads((output/'provider_profiles.json').read_text(encoding='utf-8'))
    assert profiles['llm_profiles'][0]['id']==mapping['legacy-profile']==profiles['active_llm_profile_id']
    assert profiles['llm_profiles'][0]['api_key']=='test-secret'
    monkeypatch.setenv('WRX_DB_PATH',str(output/'companion.sqlite3'))
    migrated=store.get_conversation(mapping[conv.id])
    assert migrated.character_id==mapping[old_character]
    assert [m.content for m in migrated.messages]==['保留正文','保留回复']
    assert migrated.messages[0].images==[] and migrated.messages[0].image_count==1
    assert migrated.messages[1].usage.input_tokens==42
    # 历史原始输入的完整SHA256仍匹配；不同正文仍拒绝。
    assert store.begin_turn(migrated.id,mapping['legacy-request'],'保留正文',migrated.timezone,'web','OFF',images=[PNG]) is False
    with pytest.raises(store.Conflict): store.begin_turn(migrated.id,mapping['legacy-request'],'变化正文',migrated.timezone,'web','OFF',images=[PNG])
    with store.database() as db:
        assert db.execute('SELECT fingerprint FROM requests').fetchone()[0]==old_fingerprint
        assert db.execute('SELECT vector FROM memory_vectors').fetchone()[0]=='[0.25,0.5]'
        assert db.execute('SELECT diary_date FROM diaries').fetchone()[0]=='2026-10-03'
        assert [tuple(r) for r in db.execute('SELECT * FROM sqlite_sequence')]==before_sequences
        assert 'BLOB'==next(r[2] for r in db.execute('PRAGMA table_info(requests)') if r[1]=='fingerprint')
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('deleted_memories','conversation_branches','companion_states')").fetchone()



def test_legacy_image_regeneration_replays_after_expiry(tmp_path,monkeypatch):
    from app.chat.core import core
    source=tmp_path/'source';source.mkdir()
    monkeypatch.setenv('WRX_DB_PATH',str(source/'companion.sqlite3'))
    conv=store.create_conversation()
    store.begin_turn(conv.id,'first','看图',conv.timezone,'web','OFF',images=[PNG])
    store.finish_turn('first','已看',TokenUsage(),[],[],{})
    user,assistant=store.get_conversation(conv.id).messages
    store.begin_turn(conv.id,'old-regen','看图',conv.timezone,'web','OFF',regenerate_mid=assistant.id,images=[PNG])
    store.finish_turn('old-regen','重生成',TokenUsage(),[],[],{})
    with store.database() as db: role.initialize(db)
    legacy=hashlib.sha256(store.dumps([conv.id,'看图',conv.timezone,'web','OFF',assistant.id,[PNG]]).encode()).digest()
    with store.database() as db:
        doc=json.loads(db.execute('SELECT document FROM messages WHERE id=?',(user.id,)).fetchone()[0]);doc['images']=[PNG]
        db.execute('UPDATE messages SET document=? WHERE id=?',(store.dumps(doc),user.id))
        db.execute('DELETE FROM images')
        db.execute('UPDATE requests SET fingerprint=?,fingerprint_version=1 WHERE id=?',(legacy,'old-regen'))
    output=tmp_path/'ready'/'data'
    report=prepare(source,output,store.utcnow()+timedelta(hours=4))
    assert report['verified_rekeyed_action_fingerprints']==1
    mapping=json.loads((output.parent/'data-identity-map.json').read_text(encoding='utf-8'))
    monkeypatch.setenv('WRX_DB_PATH',str(output/'companion.sqlite3'))
    monkeypatch.setattr(core,'llm_for',lambda *args:pytest.fail('完成请求重放不得调用模型'))
    job=core.submit(mapping[conv.id],mapping['old-regen'],'看图',conv.timezone,'web','OFF',regenerate_mid=mapping[assistant.id])
    assert job.task is None and store.get_request(job.request_id)['status']=='complete'
