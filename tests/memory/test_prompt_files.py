import pytest
from fastapi.testclient import TestClient
from app.memory import prompt_files,role,system
from app.character import state
from app.chat import store
from app.main import app
from app.skills import runtime

def test_markdown_live_read_overrides_old_database_text():
    cfg=role.settings()
    store.save_setting('role_memory',cfg.model_dump())
    prompt_files.write('diary','文件中定义的自定义日记')
    assert role.settings().presets['diary'].prompt=='文件中定义的自定义日记'
    prompt_files.write('system','第三人称系统记忆自定义提示词，至少二十个字符。')
    assert system.settings().prompt==prompt_files.read('system')
    prompt_files.write('emotion_summary','自定义冷却总结')
    assert state.config().summary_prompt=='自定义冷却总结'
    (runtime.ROOT/'diary-write'/'SKILL.md').write_text('自定义聊天即时日记',encoding='utf-8')
    assert runtime.read_skill('diary-write')=='自定义聊天即时日记'

def test_ui_save_uses_same_files_without_database_prompt_copies():
    cfg=role.settings();cfg.presets['diary'].prompt='页面自定义日记'
    role.save_settings(cfg.model_dump())
    assert prompt_files.read('diary')=='页面自定义日记'
    stored=store.get_setting('role_memory',{})
    assert not any(key in stored['presets']['diary'] for key in ('prompt','requirements','instant_prompt'))
    with TestClient(app) as client:
        cfg=system.settings().model_dump();cfg['prompt']='页面保存的第三人称系统记忆提示词，内容长度大于二十个字符。'
        assert client.put('/api/system-memory/settings',json=cfg).status_code==200
        assert prompt_files.read('system')==cfg['prompt']
        assert 'prompt' not in store.get_setting('system_memory',{})
        cfg=state.config().model_dump();cfg['summary_prompt']='页面保存的情绪冷却总结'
        assert client.put('/api/role-state/settings',json=cfg).status_code==200
        assert prompt_files.read('emotion_summary')==cfg['summary_prompt']
        assert 'summary_prompt' not in store.get_setting('role_emotion_settings',{})

def test_missing_empty_file_and_path_escape_do_not_fall_back():
    prompt_files.path('system').unlink()
    with pytest.raises(ValueError,match='无法读取'):system.settings()
    prompt_files.path('diary').write_text(' \n',encoding='utf-8')
    with pytest.raises(ValueError,match='为空'):role.settings()
    with pytest.raises(ValueError):prompt_files.read('../secret')
    with pytest.raises(ValueError):prompt_files.write('diary','')
