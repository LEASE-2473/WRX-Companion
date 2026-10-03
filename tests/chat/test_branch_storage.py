import sqlite3
from app.chat import store
from app.chat.storage_format import initialize_relationships
from app.models import TokenUsage


def test_legacy_branch_metadata_moves_and_deleted_backups_are_dropped():
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE conversations(id TEXT PRIMARY KEY)')
    db.executemany('INSERT INTO conversations VALUES (?)',[('parent',),('child',)])
    db.execute('CREATE TABLE conversation_branches(conversation_id TEXT,parent_conversation_id TEXT,branch_message_id TEXT)')
    db.execute("INSERT INTO conversation_branches VALUES ('child','parent','point')")
    db.execute('CREATE TABLE deleted_memories(document TEXT)')
    db.execute('CREATE TABLE companion_states(document TEXT)')
    db.execute("INSERT INTO deleted_memories VALUES ('不要的正文')")
    initialize_relationships(db)
    initialize_relationships(db)
    assert db.execute("SELECT parent_conversation_id,branch_message_id FROM conversations WHERE id='child'").fetchone()==('parent','point')
    assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('conversation_branches','deleted_memories','companion_states')").fetchall()
    db.close()


def test_branch_is_independent_copy_with_metadata_on_conversation():
    parent=store.create_conversation()
    store.begin_turn(parent.id,'initial','原正文',parent.timezone,'web','OFF')
    store.finish_turn('initial','原回复',TokenUsage(),[],[],{})
    original=store.get_conversation(parent.id)
    branch=store.branch_conversation(parent.id,original.messages[-1].id)['conversation']
    assert [m.content for m in branch.messages]==[m.content for m in original.messages]
    assert not ({m.id for m in branch.messages}&{m.id for m in original.messages})
    store.edit_user_message(branch.id,branch.messages[0].id,'分支改文')
    assert store.get_conversation(parent.id).messages[0].content=='原正文'
    with store.database() as db:
        assert tuple(db.execute('SELECT parent_conversation_id,branch_message_id FROM conversations WHERE id=?',(branch.id,)).fetchone())==(parent.id,original.messages[-1].id)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_branches'").fetchone()
    store.delete_conversation(parent.id)
    kept=store.get_conversation(branch.id)
    assert kept.messages[0].content=='分支改文' and kept.parent_conversation_id is None
