"""Migration contracts: HTTP routes, deployed resources, and cwd independence."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from fastapi.testclient import TestClient
from app.main import app
from app.config import ROOT, STATIC_DIR


def test_http_route_contract():
    expected = json.loads(Path(__file__).with_name('api_routes.json').read_text(encoding='utf-8'))
    actual = sorted([path, sorted(spec)] for path, spec in app.openapi()['paths'].items())
    assert actual == expected


def test_every_html_asset_is_served():
    html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    urls = re.findall(r'(?:src|href)=["\'](/static/[^"\']+)', html)
    client = TestClient(app)
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.content, url


def test_resources_resolve_from_another_working_directory(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT), WRX_DB_PATH=str(tmp_path / 'isolated.sqlite3'))
    code = '''
from app.main import app
from app.config import DATA_DIR, ROOT, STATIC_DIR, SKILL_DEFINITIONS_DIR
from app.memory.prompt_files import PROMPT_DIR, read
from app.skills.runtime import catalog
from app.autonomy.service import SKILLS
import importlib.util
if (ROOT / 'extensions/toy').is_dir():
    from app.tools.toy import controller, records, service
    assert (controller.TOY / 'skill/SKILL.md').is_file()
    assert records.RECORDS == ROOT / 'extensions/toy/data/records'
    assert (service.ROOT / 'panel.html').is_file()
assert DATA_DIR == ROOT / 'data'
assert (STATIC_DIR / 'index.html').is_file()
assert PROMPT_DIR == ROOT / 'app/memory/prompts'
assert read('system').strip()
assert SKILLS == SKILL_DEFINITIONS_DIR
assert {item['name'] for item in catalog()} == {'memory-read', 'diary-write'}

'''
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_directory_index_and_current_document_links_are_maintained():
    from scripts.check_structure import audit
    result = audit()
    assert result['errors'] == []
    assert result['document_links'] > 0
