import pytest
from app.chat import store as companion_store
from app.providers import profiles as provider_store
from app.prompting import preset_store as prompt_store
from app.prompting import lorebook_store
from app.settings import store as runtime_settings_store


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    import shutil
    from app.memory import prompt_files
    isolated_prompts=tmp_path / 'memory-prompts'
    shutil.copytree(prompt_files.PROMPT_DIR,isolated_prompts)
    monkeypatch.setattr(prompt_files,'PROMPT_DIR',isolated_prompts)
    from app.skills import runtime as skill_runtime
    isolated_skills=tmp_path / 'skills'
    shutil.copytree(skill_runtime.ROOT.parent,isolated_skills)
    monkeypatch.setattr(skill_runtime,'ROOT',isolated_skills / 'definitions')
    monkeypatch.setenv('WRX_DB_PATH', str(tmp_path / 'companion.sqlite3'))
    monkeypatch.setattr(companion_store, 'CONVERSATIONS_FILE', tmp_path / 'legacy.json')
    monkeypatch.setattr(provider_store, 'PROVIDER_PROFILES_FILE', tmp_path / 'providers.json')
    monkeypatch.setattr(prompt_store, 'WRX_PROMPT_PRESETS_FILE', tmp_path / 'prompts.json')
    monkeypatch.setattr(lorebook_store, 'WRX_LOREBOOKS_FILE', tmp_path / 'lorebooks.json')
    monkeypatch.setattr(runtime_settings_store, 'WRX_RUNTIME_SETTINGS_FILE', tmp_path / 'runtime.json')
    from app.memory import vector_store
    monkeypatch.setattr(vector_store, 'VECTOR_MEMORY_FILE', tmp_path / 'vectors.json')

    from app.skills import configuration
    from app.extensions import manager
    monkeypatch.setattr(configuration,'FILE',tmp_path / 'skills_config.json')
    monkeypatch.setattr(manager,'CONFIG',tmp_path / 'extensions_config.json')
    monkeypatch.setattr(manager,'DIRECTORY',tmp_path / 'extensions')
    monkeypatch.setattr(manager,'_instances',{})
    monkeypatch.setattr(manager,'_revisions',{})
