"""只读取声明；显式启用、按需启动，不扫描设备或接管外部进程。"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import httpx
from app.config import ROOT, DATA_DIR
from .schema import ExtensionManifest, local_file

DIRECTORY = ROOT / 'extensions'
CONFIG = DATA_DIR / 'extensions_config.json'
HOST_PORT = 2473
_instances = {}
_revisions = {}
_lock = threading.RLock()


def config():
    if not CONFIG.exists(): return {}
    value = json.loads(CONFIG.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or any(type(v) is not bool for v in value.values()): raise ValueError('扩展配置必须是布尔值映射')
    return value


def scan():
    result = {}
    for path in sorted(DIRECTORY.glob('*/extension.json')):
        try:
            local_file(DIRECTORY, str(path.relative_to(DIRECTORY)))
            manifest = ExtensionManifest.model_validate_json(path.read_text(encoding='utf-8'))
            if manifest.id != path.parent.name: raise ValueError('目录名必须与 ID 一致')
            skill_file = local_file(path.parent, manifest.skill_path)
            if skill_file.stat().st_size > 65536: raise ValueError('Skill 说明超过64 KiB')
            for argument in manifest.entry_cmd[1:]:
                if argument.endswith('.py'): local_file(path.parent,argument)
            result[manifest.id] = {'manifest':manifest, 'directory':path.parent, 'error':None}
        except Exception as exc:
            result[path.parent.name] = {'manifest':None, 'directory':path.parent, 'error':str(exc)}
    ports, tags = {}, {}
    for eid, item in result.items():
        m = item['manifest']
        if not m: continue
        if m.internal_port == HOST_PORT: item['error'] = f'端口与主项目 {HOST_PORT} 冲突'
        for value, mapping, label in ((m.internal_port, ports, '端口'), (m.invocation.tag, tags, '标签')):
            if value in mapping:
                other = mapping[value]
                item['error'] = f'{label}与扩展 {other} 冲突'
                result[other]['error'] = f'{label}与扩展 {eid} 冲突'
            else: mapping[value] = eid
    return result


def get(eid, enabled=False):
    item = scan().get(eid)
    if not item: raise ValueError('扩展不存在')
    if item['error']: raise ValueError(item['error'])
    if enabled and not config().get(eid, False): raise ValueError('扩展已停用')
    return item


def listing():
    settings = config()
    return [dict(id=eid, name=item['manifest'].name if item['manifest'] else eid,
                 icon=item['manifest'].icon if item['manifest'] else '🧩',
                 description=item['manifest'].description if item['manifest'] else '',
                 has_panel=bool(item['manifest'] and item['manifest'].has_panel),
                 enabled=bool(settings.get(eid)), running=running(eid),
                 error=item['error'] or _instances.get(eid, {}).get('error'))
            for eid,item in scan().items()]


def running(eid):
    child = _instances.get(eid, {}).get('child')
    return bool(child and child.poll() is None)


def set_enabled(eid, enabled):
    with _lock:
        if enabled: get(eid)
        elif eid not in scan() and eid not in _instances: raise ValueError('扩展不存在')
        settings = config()
        if not enabled:
            # 先撤销调用权限，即使业务关闭失败，也不能继续向它发送动作。
            settings[eid] = False
            write_config(settings)
            _revisions[eid] = _revisions.get(eid,0) + 1
            stop(eid)
            return
        settings[eid] = bool(enabled)
        _revisions[eid] = _revisions.get(eid,0) + 1
        write_config(settings)


def write_config(settings):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        temp = CONFIG.with_suffix('.tmp')
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(CONFIG)


def start(eid):
    with _lock:
        item = get(eid, True); m = item['manifest']
        if running(eid):
            if _instances[eid]['manifest'] != m: raise ValueError('扩展配置已修改，请关闭后重新启动')
            return
        # 不复用端口上的未知服务，只启动自己拥有的进程。
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1', m.internal_port))
            except OSError as exc: raise ValueError(f'端口 {m.internal_port} 已被占用，请修改扩展端口并重新注册') from exc
        cmd = [sys.executable if p == '{python}' else p for p in m.entry_cmd]
        token = secrets.token_urlsafe(32)
        env = dict(os.environ, WRX_EXTENSION_TOKEN=token)
        logs = DATA_DIR / 'extensions' / eid; logs.mkdir(parents=True, exist_ok=True)
        with (logs / 'service.log').open('ab') as output:
            child = subprocess.Popen(cmd, cwd=item['directory'], env=env, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        instance = {'child':child, 'token':token, 'manifest':m, 'lease':secrets.token_hex(16), 'error':None}
        _instances[eid] = instance
        for _ in range(50):
            if child.poll() is not None: break
            try:
                request(eid, '/api/health', method='GET', timeout=.3)
                return
            except (httpx.HTTPError, ValueError): time.sleep(.1)
        instance['error'] = '启动失败／无法连接，请检查扩展配置及日志'
        if child.poll() is None: child.terminate(); child.wait(timeout=5)
        raise ValueError(instance['error'])


def request(eid, path, data=None, method='POST', timeout=60, generation=None):
    instance = _instances.get(eid)
    if not instance or not running(eid): raise ValueError('扩展未运行')
    m = instance['manifest']
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        headers = {'X-Extension-Token':instance['token']}
        if generation is not None: headers['X-Extension-Generation'] = str(generation)
        response = client.request(method, f'http://127.0.0.1:{m.internal_port}{path}',
            json=data if method != 'GET' else None, headers=headers)
        response.raise_for_status()
        if len(response.content) > 65536: raise ValueError('扩展结果超过64 KiB')
        return response.json()


def stop(eid):
    with _lock:
        _revisions[eid] = _revisions.get(eid,0) + 1
        instance = _instances.get(eid)
        if not instance: return
        if running(eid):
            # 扩展负责业务关闭（toy：取消DIY、STOP、断开）。失败仍显示，不自动重放。
            try: request(eid, instance['manifest'].shutdown_path, {})
            except Exception as exc:
                instance['error'] = '扩展关闭未确认：' + str(exc)
                raise ValueError(instance['error']) from exc
            try: instance['child'].wait(timeout=5)
            except subprocess.TimeoutExpired:
                instance['child'].terminate(); instance['child'].wait(timeout=5)
        _instances.pop(eid, None)


def invoke(eid, data, revision, definition, original_lease, generation):
    with _lock:
        m = get(eid,True)['manifest']
        if revision != _revisions.get(eid,0) or definition != m.model_dump_json() or original_lease != _instances.get(eid,{}).get('lease'):
            raise ValueError('扩展配置或连接已变更，本轮调用失效')
        start(eid)
        return request(eid,m.invocation.endpoint,data,generation=generation)


def shutdown():
    for eid in list(_instances):
        try: stop(eid)
        except Exception:
            instance = _instances.get(eid)
            if instance and instance['child'].poll() is None:
                instance['child'].terminate()
                try: instance['child'].wait(timeout=5)
                except subprocess.TimeoutExpired: instance['child'].kill()
            _instances.pop(eid,None)
