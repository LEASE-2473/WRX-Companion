import hashlib
from datetime import timedelta

import pytest

from app.chat import store
from app.memory.role import initialize
from app.models import TokenUsage
from scripts.prepare_deployment_data import prepare


def test_offline_preparation_preserves_source_and_message_payload(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    db_path = source / 'companion.sqlite3'
    monkeypatch.setenv('WRX_DB_PATH', str(db_path))
    with store.database() as db:
        initialize(db)
    cid = store.create_conversation().id
    assert store.begin_turn(cid, 'old-request', '历史正文', 'Asia/Shanghai', 'web', 'off')
    store.finish_turn('old-request', '回复正文', TokenUsage(), [], [],
                      {'reply': '回复正文', 'debug': {'llm_messages': ['重复提示词' * 100000]}})
    with store.database() as db:
        db.execute('UPDATE requests SET finished_at=?', ((store.utcnow()-timedelta(hours=2)).isoformat(),))
    # 源配置逐字节复制，不需要模型或启动服务。
    config = source / 'provider_profiles.json'
    config.write_text('{"profiles":[]}', encoding='utf-8')
    before = db_path.read_bytes()
    result = prepare(source, tmp_path / 'prepared' / 'data')
    assert result['integrity_check'] == 'ok'
    assert result['foreign_key_check'] == 'ok'
    assert result['original_sha256'] == hashlib.sha256(before).hexdigest()
    assert db_path.read_bytes() == before
    assert (tmp_path / 'prepared/data/provider_profiles.json').read_bytes() == config.read_bytes()
    assert result['preserved_tables']['messages']['rows'] == 2
    assert result['cleanup']['expired_request_debug'] == 0
    assert result['output_bytes'] > 0
    monkeypatch.setenv('WRX_DB_PATH', str(tmp_path / 'prepared/data/companion.sqlite3'))
    assert store.get_request('old-request',include_debug=True)['debug'] is not None
    assert store.begin_turn(cid, 'old-request', '历史正文', 'Asia/Shanghai', 'web', 'off') is False
    assert len(store.get_conversation(cid).messages) == 2
    with pytest.raises(ValueError, match='已存在'):
        prepare(source, tmp_path / 'prepared/data')
    with pytest.raises(ValueError, match='独立'):
        prepare(source, source / 'prepared')
