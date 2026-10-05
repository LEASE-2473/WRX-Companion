import json
import asyncio
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip('extensions.toy', reason='未安装独立toy扩展')
from app.tools.toy import controller


@pytest.mark.parametrize('stop_fails', [False, True])
def test_service_close_stops_scanner_and_disconnects_even_if_stop_fails(monkeypatch, stop_fails):
    from app.tools.toy import service
    bridge = service.Bridge()
    scanner = SimpleNamespace(stop=AsyncMock())
    client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
    bridge.scanner, bridge.client, bridge.writer = scanner, client, object()
    packets = []
    def dispatch(packet, label):
        packets.append(packet)
        if stop_fails:
            raise RuntimeError('write failed')
        bridge.last_command = {'write_ack':True}
    monkeypatch.setattr(bridge, 'dispatch', dispatch)
    monkeypatch.setattr(service, 'save', lambda *args: None)
    result = asyncio.run(bridge.close())
    assert result['closed'] and bool(result['warnings']) == stop_fails
    assert packets == [service.STOP]
    scanner.stop.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert bridge.client is None and bridge.scanner is None
    with pytest.raises(RuntimeError, match='关闭'):
        asyncio.run(bridge.action('scan', {}))


def test_packaged_runtime_without_development_directory(tmp_path):
    source = Path(__file__).resolve().parents[2] / 'app'
    shutil.copytree(source, tmp_path / 'app', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(source.parent / 'extensions',tmp_path / 'extensions',ignore=shutil.ignore_patterns('__pycache__','data','.git'))
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
assert records.RECORDS == Path.cwd() / 'extensions/toy/data/records'
server = service.ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
service.PORT = server.server_address[1]
controller.BASE = f'http://127.0.0.1:{service.PORT}'
threading.Thread(target=service.run_loop, daemon=True).start()
def serve():
    try:
        server.serve_forever()
    finally:
        server.server_close()
server_thread = threading.Thread(target=serve, daemon=True)
server_thread.start()
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
    result = controller.close('test')
    assert not result['attached'] and not result['service_running']
    assert service.bridge.closing
    server_thread.join(timeout=3)
    assert not server_thread.is_alive()
finally:
    server.shutdown()
    server.server_close()
    service.loop.call_soon_threadsafe(service.loop.stop)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['connected'] is False
