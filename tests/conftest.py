import pytest
from app import companion_store, provider_store, prompt_store, lorebook_store, runtime_settings_store


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('WRX_DB_PATH', str(tmp_path / 'companion.sqlite3'))
    monkeypatch.setattr(companion_store, 'CONVERSATIONS_FILE', tmp_path / 'legacy.json')
    monkeypatch.setattr(provider_store, 'PROVIDER_PROFILES_FILE', tmp_path / 'providers.json')
    monkeypatch.setattr(prompt_store, 'WRX_PROMPT_PRESETS_FILE', tmp_path / 'prompts.json')
    monkeypatch.setattr(lorebook_store, 'WRX_LOREBOOKS_FILE', tmp_path / 'lorebooks.json')
    monkeypatch.setattr(runtime_settings_store, 'WRX_RUNTIME_SETTINGS_FILE', tmp_path / 'runtime.json')
