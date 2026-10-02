import json
from pathlib import Path
import shutil
import subprocess
import sys

from app.tools.toy import controller


def test_start_uses_application_python_and_module(monkeypatch, tmp_path):
    calls = []
    pages = iter([False, True])

    def page():
        if not next(pages):
            raise OSError('not running')
        return '', 'token'

    monkeypatch.setattr(controller, 'ROOT', tmp_path)
    monkeypatch.setattr(controller, '_enabled', False)
    monkeypatch.setattr(controller, '_child', None)
    monkeypatch.setattr(controller, 'page', page)
    monkeypatch.setattr(controller, 'refresh', lambda: {})
    monkeypatch.setattr(controller.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    controller.start('test')
    args, kwargs = calls[0]
    assert args[0] == [sys.executable, '-m', 'app.tools.toy.service', '--no-browser']
    assert kwargs['cwd'] == tmp_path
    assert (tmp_path / 'data/toy/main-project-child.log').exists()


def test_packaged_runtime_without_development_directory(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'app'
    shutil.copytree(source, tmp_path / 'app', ignore=shutil.ignore_patterns('__pycache__'))
    script = '''
import asyncio
import json
from pathlib import Path
import threading
import urllib.request
from app.tools.toy import controller, service, records
assert not Path('Toy connection').exists()
assert len(controller.definitions()) == 10
assert controller.SKILL.read_text(encoding='utf-8').startswith('---')
assert len(service.MODES) == 8
assert not service.bridge.client and not service.bridge.scanner
assert records.RECORDS.is_relative_to(Path.cwd() / 'data')
server = service.ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
service.PORT = server.server_address[1]
controller.BASE = f'http://127.0.0.1:{service.PORT}'
threading.Thread(target=service.run_loop, daemon=True).start()
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    html, token = controller.page()
    assert token and '<html' in html.lower()
    state = controller.request('state')
    assert not state['connected'] and not state['control_ready']
    controller._enabled = True
    assert asyncio.run(controller.prepare('test')) is None
    controller._enabled = False
    assert asyncio.run(controller.prepare('test')) is None
    print(json.dumps({'modes': len(service.MODES), 'connected': state['connected']}))
finally:
    server.shutdown()
    server.server_close()
    service.loop.call_soon_threadsafe(service.loop.stop)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['connected'] is False
