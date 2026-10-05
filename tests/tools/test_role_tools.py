import asyncio
import json
import time
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app.chat import store
pytest.importorskip('extensions.toy', reason='未安装独立toy扩展')
from app.tools.toy import controller as tools
from app.main import app
from app.models import LlmProviderProfile, TokenUsage
from app.providers.client import OpenAICompatibleLlm, ProviderError
from app.chat.core import core


@pytest.fixture(autouse=True)
def reset_bridge(monkeypatch):
    monkeypatch.setattr(tools, '_enabled', False)
    monkeypatch.setattr(tools, '_lease', 0)
    monkeypatch.setattr(tools, '_cache', {})
    monkeypatch.setattr(tools, '_cache_at', 0)
    monkeypatch.setattr(tools, '_program', {})
    monkeypatch.setattr(tools, '_child', None)
    monkeypatch.setattr(tools, '_panel_token', 'test-panel-token')


def ready():
    return {'revision':'fake', 'connected':True, 'control_ready':True,
            'selected':{'name':'fake'}, 'playback':{'status':'stopped'}}


def test_close_disables_skill_and_stale_controls_then_can_restart(monkeypatch):
    import threading
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, '_program_cancel', threading.Event())
    monkeypatch.setattr(tools, '_program', {'status':'running'})
    lease, token = tools._lease, tools._panel_token
    actions = []
    monkeypatch.setattr(tools, 'request', lambda action, args=None: actions.append(action) or {'closed':True})
    def stopped():
        raise ConnectionRefusedError()
    monkeypatch.setattr(tools, 'page', stopped)
    result = tools.close('test')
    assert not result['attached'] and not result['service_running']
    assert tools._program_cancel.is_set() and tools._lease != lease
    assert asyncio.run(tools.prepare('test')) is None
    with pytest.raises(ValueError):
        tools.panel_request(token, 'intensity', {})
    assert actions == ['shutdown']
    monkeypatch.setattr(tools, 'page', lambda: ('', 'token'))
    monkeypatch.setattr(tools, 'request', lambda *args: ready())
    assert tools.start('test')['ready']
    with pytest.raises(ValueError):
        tools.execute('test', lease, 'toy_stop', {})


def test_close_failure_remains_visible_and_retryable(monkeypatch):
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, 'request', lambda *args: {'error':'failed'})
    with pytest.raises(ValueError, match='关闭未确认'):
        tools.close('test')
    assert not tools._enabled
    assert tools.status('test')['service_running']
    assert tools.status('test')['error']
    assert asyncio.run(tools.prepare('test')) is None


def test_main_shutdown_waits_for_owned_service_and_preserves_warning(monkeypatch):
    waited = []
    child = SimpleNamespace(poll=lambda: None, wait=lambda timeout: waited.append(timeout))
    monkeypatch.setattr(tools, '_child', child)
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, 'request', lambda *args: {'closed':True, 'warnings':['停止写入未确认']})
    tools.shutdown()
    assert waited == [5] and tools._child is None
    assert not tools._enabled and not tools.status('test')['service_running']
    assert tools.status('test')['warning'] == '停止写入未确认'




def test_late_refresh_cannot_restore_closed_state(monkeypatch):
    monkeypatch.setattr(tools, '_enabled', True)
    def request(*args):
        tools._enabled = False
        tools._lease += 1
        tools.remember({})
        return ready()
    monkeypatch.setattr(tools, 'request', request)
    tools.refresh()
    assert not tools.status('test')['service_running']




def test_prepare_gate_execution_recheck_and_scope(monkeypatch):
    cid = 'current'
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, 'request', lambda *a: ready())
    prepared = asyncio.run(tools.prepare(cid))
    assert len(prepared['tools']) == 10 and '已连接设备工具' in prepared['prompt']
    assert asyncio.run(tools.prepare('other'))['tools'] == prepared['tools']
    monkeypatch.setattr(tools, 'request', lambda *a:{'connected':False})
    with pytest.raises(ValueError, match='未连接'):
        tools.execute(cid, prepared['lease'], 'toy_stop', {})
    assert asyncio.run(tools.prepare(cid)) is None
    with pytest.raises(ValueError): tools.validate('toy_set_intensity', {'channel1':True,'channel2':0,'channel3':0})
    with pytest.raises(ValueError): tools.validate('toy_stop', {'code':'anything'})
    with pytest.raises(ValueError): tools.execute('other', 0, 'toy_stop', {})






@pytest.mark.parametrize('args', [
    {'frames':[[1,0,0]], 'frame_ms':125, 'duration_seconds':10},
    {'frames':[[True,0,0]], 'frame_ms':125, 'duration_seconds':10},
    {'frames':[[15,0]], 'frame_ms':125, 'duration_seconds':10},
    {'frames':[], 'frame_ms':125, 'duration_seconds':10},
    {'frames':[[15,0,0]], 'frame_ms':64, 'duration_seconds':10},
    {'frames':[[15,0,0]], 'frame_ms':125, 'duration_seconds':601},
    {'frames':[[15,0,0]], 'frame_ms':125, 'duration_seconds':10, 'code':'x'},
])
def test_sequence_rejects_invalid_program(args):
    with pytest.raises(ValueError):
        tools.validate('toy_play_sequence', args)


def test_portable_schema_keeps_strict_server_intensity_validation():
    schemas = json.dumps(tools.definitions())
    assert 'anyOf' not in schemas
    for value in (1, 14, 101, True):
        with pytest.raises(ValueError):
            tools.validate('toy_set_intensity', {'channel1':value,'channel2':0,'channel3':0})
    for value in (0, 15, 100):
        tools.validate('toy_set_intensity', {'channel1':value,'channel2':0,'channel3':0})


@pytest.mark.parametrize('ack', [True, False])
def test_sequence_order_deadline_and_failed_write(monkeypatch, ack):
    clock = [0.0]
    actions = []
    class Cancel:
        cancelled = False
        def is_set(self): return self.cancelled
        def set(self): self.cancelled = True
        def wait(self, seconds):
            clock[0] += seconds
            return self.cancelled
    cancel = Cancel()
    monkeypatch.setattr(tools, 'time', SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, '_program_cancel', cancel)
    monkeypatch.setattr(tools, '_program', {'status':'running'})
    def request(action, args=None):
        actions.append((action, args))
        return {**ready(), 'last_command':{'accepted_at':'frame', 'write_ack':ack}}
    monkeypatch.setattr(tools, 'request', request)
    tools.run_program('current', 0, cancel, [[15,0,0],[0,15,0]], 250, 5)
    assert actions[-1][0] == 'stop'
    frames = [args for action,args in actions if action == 'intensity']
    if ack:
        assert len(frames) == 20
        assert [frame['channel1'] for frame in frames] == [15,0] * 10
        assert tools._program['status'] == 'finished'
        assert clock[0] == 5
    else:
        assert len(frames) == 1
        assert tools._program['status'] == 'error'
        assert '未确认' in tools._program['error']


def test_manual_control_cancels_sequence_and_stale_panel_rejected(monkeypatch):
    import threading
    cancel = threading.Event()
    monkeypatch.setattr(tools, '_program_cancel', cancel)
    monkeypatch.setattr(tools, '_program', {'status':'running'})
    actions = []
    monkeypatch.setattr(tools, 'request', lambda action, args=None: actions.append(action) or ready())
    with pytest.raises(ValueError):
        tools.panel_request('old-token', 'stop', {})
    assert not cancel.is_set() and not actions
    tools.panel_request(tools._panel_token, 'stop', {})
    assert cancel.is_set() and actions == ['stop']
    assert tools._program['status'] == 'cancelled'


def test_skill_scope_and_snapshot(monkeypatch):
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, 'request', lambda *args:{**ready(), 'intensity':[15,0,0]})
    prepared = asyncio.run(tools.prepare('current'))
    assert 'toy_play_sequence' in prepared['prompt']
    assert '本轮设备状态快照' in prepared['prompt']
    assert '[15, 0, 0]' in prepared['prompt']
    assert asyncio.run(tools.prepare('other'))['tools'] == prepared['tools']




def test_reconnect_invalidates_prepared_call(monkeypatch):
    monkeypatch.setattr(tools, '_enabled', True)
    actions = []
    monkeypatch.setattr(tools, 'request', lambda action, args=None: actions.append(action) or ready())
    prepared = asyncio.run(tools.prepare('current'))
    tools.panel_request(tools._panel_token, 'disconnect', {})
    tools.panel_request(tools._panel_token, 'connect', {})
    with pytest.raises(ValueError, match='失效'):
        tools.execute('current', prepared['lease'], 'toy_stop', {})
    assert actions == ['state','disconnect','connect']


def test_diy_query_does_not_interrupt_inflight_frame(monkeypatch):
    monkeypatch.setattr(tools, '_program', {'status':'running'})
    actions = []
    monkeypatch.setattr(tools, 'request', lambda action, args=None: actions.append(action) or ready())
    with pytest.raises(ValueError, match='DIY'):
        tools.panel_request(tools._panel_token, 'battery', {})
    assert not actions


def test_global_open_preserves_program_and_other_sessions_can_stop(monkeypatch):
    import threading
    cancel = threading.Event()
    monkeypatch.setattr(tools, '_enabled', True)
    monkeypatch.setattr(tools, '_program_cancel', cancel)
    monkeypatch.setattr(tools, '_program', {'status':'running'})
    monkeypatch.setattr(tools, 'page', lambda:("const token='secret'", 'secret'))
    actions = []
    monkeypatch.setattr(tools, 'request', lambda action, args=None: actions.append(action) or ready())
    prepared = asyncio.run(tools.prepare('first'))
    token = tools._panel_token
    tools.start('second')
    assert tools._panel_token == token and tools._lease == prepared['lease']
    assert not cancel.is_set() and tools._program['status'] == 'running'
    assert tools.status('first')['ready'] and tools.status('second')['ready']
    tools.execute('second', prepared['lease'], 'toy_stop', {})
    assert cancel.is_set() and actions[-1] == 'stop'
    assert all(action in {'state','stop'} for action in actions)




@pytest.mark.parametrize('status', [200, 503])
def test_text_fallback_is_exactly_one_http_request(status):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(status, text='data: [DONE]\n\n')
    async def scenario():
        llm = OpenAICompatibleLlm(LlmProviderProfile(id='x', name='x', api_key='fake', model='fake'))
        llm.single_text_attempt = True
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            llm.client = lambda: client
            with pytest.raises((ProviderError, httpx.HTTPStatusError)):
                _ = [part async for part in llm.stream_complete([])]
        assert len(requests) == 1
        assert 'tools' not in requests[0]
    asyncio.run(scenario())
