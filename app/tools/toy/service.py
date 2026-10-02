"""仅监听本机的独立 BLE 连接面板。"""
import asyncio
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import random
import threading
import time
import webbrowser

from bleak import BleakClient, BleakScanner
from .records import save
from .protocol import NAME, SERVICE, WRITE_UUID, NOTIFY_UUID, STOP, BATTERY, FUNCTION_STATUS, intensity

ROOT = Path(__file__).resolve().parent / "resources"
PORT = 8767
REVISION = 'rock-solid-20261002-8'
TOKEN = secrets.token_urlsafe(32)
MODE_DATA = json.loads((ROOT / "classic_modes.json").read_text(encoding="utf-8"))
MODES = MODE_DATA["modes"]
SPEEDS = MODE_DATA["speed"]


class Bridge:
    def __init__(self):
        self.devices = {}
        self.rows = []
        self.client = None
        self.selected = None
        self.services = []
        self.logs = deque(maxlen=150)
        self.battery = None
        self.lock = asyncio.Lock()
        self.last_command = None
        self.notify_client = None
        self.writer = None
        self.setup_task = None
        self.pending = set()
        self.function_status = None
        self.current_intensity = [0, 0, 0]
        self.mode_task = None
        self.playback = dict(status='stopped', mode_id=None, frame=0, speed_index=3, repeat='single')
        self.random_order = []
        while len(self.random_order) < len(MODES):
            value = MODES[int(random.random() * len(MODES))]['id']
            if value not in self.random_order:
                self.random_order.append(value)
        self.previous_frame = None
        self.notifications = deque(maxlen=150)
        self.scanner = None
        self.scan_task = None
        self.worker = None
        self.pending_target = None
        self.pending_stop = None
        self.mode_queue = deque(maxlen=6)
        self.query_queue = {}
        self.last_control_clock = 0
        self.inflight_control = False
        self.inflight_task = None
        self.inflight_is_query = False

    def log(self, message):
        self.logs.append(f'{datetime.now():%H:%M:%S}  {message}')

    def state(self):
        connected = bool(self.client and self.client.is_connected)
        return dict(revision=REVISION, connected=connected, selected=self.selected, devices=self.rows,
                    services=self.services if connected else [],
                    battery=self.battery if connected else None, logs=list(self.logs),
                    busy=self.lock.locked(), scanning=self.scanner is not None, last_command=self.last_command,
                    control_ready=connected and self.writer is not None,
                    feedback_ready=connected and self.notify_client is self.client,
                    pending_writes=len(self.pending),
                    queued_target=self.pending_target is not None,
                    queued_stop=self.pending_stop is not None,
                    queued_frames=len(self.mode_queue), queued_queries=len(self.query_queue),
                    function_status=self.function_status,
                    intensity=self.current_intensity, playback=dict(self.playback),
                    modes=[{k: v for k, v in mode.items() if k != 'wave'} for mode in MODES],
                    speed_ms=SPEEDS)

    async def action(self, command, data):
        if command == 'state':
            return self.state()
        if self.lock.locked():
            raise RuntimeError('上一个操作仍在进行，请稍候。')
        async with self.lock:
            try:
                if command == 'scan':
                    if self.client and self.client.is_connected:
                        raise RuntimeError('请先断开连接，再重新扫描。')
                    if self.scanner is None:
                        self.devices = {}
                        self.rows = []
                        self.scanner = BleakScanner(detection_callback=self.discovered)
                        try:
                            await self.scanner.start()
                        except BaseException:
                            self.scanner = None
                            raise
                        self.log('实时扫描已开始，发现设备立即显示。')
                        self.scan_task = asyncio.create_task(self.scan_window())
                elif command == 'scan-stop':
                    await self.stop_scan()
                elif command == 'connect':
                    if self.client and self.client.is_connected:
                        raise RuntimeError('请先断开当前设备。')
                    pair = self.devices.get(data.get('address'))
                    if not pair:
                        raise RuntimeError('请先扫描并选择设备。')
                    await self.stop_scan()
                    device, adv = pair
                    self.selected = dict(address=device.address, name=adv.local_name or device.name or '')
                    self.battery = None
                    self.services = []
                    self.log(f'正在连接 {self.selected["name"] or device.address}…')
                    client = BleakClient(device, disconnected_callback=self.on_disconnected)
                    self.client = client
                    self.clear_waiting('更换用户连接')
                    self.worker = None
                    self.notify_client = None
                    self.writer = None
                    try:
                        await asyncio.wait_for(client.connect(), 30)
                        self.services = [dict(uuid=s.uuid, characteristics=[
                            dict(uuid=c.uuid, handle=c.handle, properties=c.properties)
                            for c in s.characteristics]) for s in client.services]
                        save('web-gatt', dict(**self.selected, services=self.services))
                        self.log('连接成功，已枚举服务。')
                        if self.selected['name'] == NAME:
                            self.bind_control(client)
                            self.setup_task = asyncio.create_task(self.activate_control(client))
                            self.setup_task.add_done_callback(self.setup_finished)
                            self.dispatch(FUNCTION_STATUS, '连接后查询功能状态')
                    except BaseException:
                        if not client.is_connected:
                            self.client = None
                        else:
                            self.log('连接已建立，初始化未完成；保留用户连接。')
                        raise
                elif command == 'disconnect':
                    self.end_mode()
                    self.clear_waiting('用户断开')
                    if self.client:
                        await asyncio.wait_for(self.client.disconnect(), 10)
                    self.client = None
                    self.battery = None
                    self.log('连接已释放。')
                elif command == 'battery':
                    self.dispatch(BATTERY, '查询电量')
                elif command == 'function-status':
                    self.dispatch(FUNCTION_STATUS, '查询功能状态')
                elif command == 'intensity':
                    if set(data) != {'channel1', 'channel2', 'channel3'}:
                        raise ValueError('必须提供三个通道的完整强度。')
                    packet = intensity(**data)
                    self.end_mode()
                    self.dispatch(packet, '设置通道强度')
                    self.current_intensity = [data['channel1'], data['channel2'], data['channel3']]
                elif command == 'stop':
                    self.end_mode()
                    self.dispatch(STOP, '停止全部运动通道')
                    self.current_intensity = [0, 0, 0]
                elif command == 'play-mode':
                    self.play_mode(data)
                elif command == 'pause-mode':
                    self.end_mode(paused=True)
                    self.dispatch(STOP, '暂停模式并停止')
                    self.current_intensity = [0, 0, 0]
                elif command == 'resume-mode':
                    if self.playback['status'] != 'paused':
                        raise ValueError('没有已暂停的模式。')
                    self.play_mode(self.playback, resume=True)
                elif command == 'speed':
                    value = data.get('speed_index')
                    if type(value) is not int or not 0 <= value <= 9:
                        raise ValueError('速度索引为0–9。')
                    self.playback['speed_index'] = value
                    if self.playback['status'] == 'playing':
                        if self.mode_task:
                            self.mode_task.cancel()
                        self.mode_task = asyncio.create_task(self.run_mode(self.client))
                else:
                    raise RuntimeError('未知操作。')
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                self.log(f'失败：{message}')
                raise RuntimeError(message) from exc
        return self.state()

    def discovered(self, device, adv):
        self.devices[device.address] = (device, adv)
        self.rows = [dict(address=d.address, name=a.local_name or d.name or '',
                          rssi=a.rssi, target=(a.local_name or d.name or '') == NAME,
                          services=a.service_uuids) for d, a in self.devices.values()]
        self.rows.sort(key=lambda r: (not r['target'], -r['rssi']))

    async def scan_window(self):
        await asyncio.sleep(20)
        await self.stop_scan()

    async def stop_scan(self):
        if self.scan_task and self.scan_task is not asyncio.current_task():
            self.scan_task.cancel()
        self.scan_task = None
        if self.scanner:
            scanner, self.scanner = self.scanner, None
            await scanner.stop()
            save('web-scan', self.rows)
            self.log(f'扫描结束：{len(self.rows)} 个设备。')

    def end_mode(self, paused=False):
        if self.mode_task:
            self.mode_task.cancel()
            self.mode_task = None
        self.playback['status'] = 'paused' if paused else 'stopped'
        while self.mode_queue:
            self.finish_waiting(self.mode_queue.popleft(), '模式已结束')
        self.previous_frame = None

    def play_mode(self, data, resume=False):
        mode_id = data.get('mode_id')
        mode = next((mode for mode in MODES if mode['id'] == mode_id), None)
        speed = data.get('speed_index', 3)
        repeat = data.get('repeat', 'single')
        if not mode or type(speed) is not int or not 0 <= speed <= 9 or repeat not in ('single', 'sequential', 'random'):
            raise ValueError('模式／速度／循环参数无效。')
        if not self.client or not self.client.is_connected or self.writer is None:
            raise RuntimeError('请由用户先连接具有正确写入特征的设备。')
        frame = self.playback['frame'] if resume else 0
        if not resume and mode_id == self.playback['mode_id']:
            return
        was_playing = self.mode_task is not None
        self.end_mode()
        if was_playing and not resume:
            self.dispatch(STOP, '切换正在播放的模式前停止')
        self.playback.update(status='playing', mode_id=mode_id, frame=frame, speed_index=speed, repeat=repeat)
        self.mode_task = asyncio.create_task(self.run_mode(self.client))

    async def run_mode(self, client):
        try:
            while self.client is client and client.is_connected:
                await asyncio.sleep(SPEEDS[self.playback['speed_index']] / 1000)
                mode = next(mode for mode in MODES if mode['id'] == self.playback['mode_id'])
                index = self.playback['frame']
                if index >= len(mode['wave']):
                    index = 0
                    if self.playback['repeat'] != 'single':
                        order = self.random_order if self.playback['repeat'] == 'random' else [m['id'] for m in MODES]
                        mode_id = order[(order.index(mode['id']) + 1) % len(order)]
                        self.playback['mode_id'] = mode_id
                        mode = next(m for m in MODES if m['id'] == mode_id)
                values = list(map(int, mode['wave'][index].split(',')))
                if values != self.previous_frame:
                    self.dispatch(intensity(*values), '模式帧强度', remember=False)
                    self.current_intensity = values
                    self.previous_frame = values
                self.playback['frame'] = index + 1
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.playback['status'] = 'error'
            self.log(f'模式播放错误：{exc}')

    def on_disconnected(self, client):
        if client is self.client:
            self.end_mode()
            self.clear_waiting('连接已断开')
            self.notify_client = None
            self.writer = None
            self.log('设备已断开；等待用户手动操作，不自动重连。')

    def setup_finished(self, task):
        if not task.cancelled() and task.exception():
            self.log(f'通知初始化失败：{task.exception()}；未主动断开。')

    def bind_control(self, client):
        service = client.services.get_service(SERVICE)
        if service is None:
            raise RuntimeError('缺少源码要求的FFE0服务。')
        writers = [c for c in service.characteristics if 'write' in c.properties]
        notifiers = [c for c in service.characteristics if 'notify' in c.properties]
        if len(writers) != 1 or len(notifiers) != 1 or writers[0].uuid.lower() != WRITE_UUID or notifiers[0].uuid.lower() != NOTIFY_UUID:
            raise RuntimeError('GATT与用户实机记录的FFE0／FFE2写入／FFE1通知不一致，未发送指令。')
        self.writer = writers[0]
        return notifiers[0]

    async def activate_control(self, client):
        notifier = self.bind_control(client)

        def receive(sender, payload):
            if self.client is not client:
                return
            packet = bytes(payload)
            self.notifications.append(dict(uuid=sender.uuid, hex=packet.hex()))
            self.log('收到通知：' + packet.hex(' '))
            if packet[:2] == b'\x55\x80' and len(packet) >= 6:
                self.battery = packet[5]
                self.log(f'电量字段：{self.battery}（原始值）')
            elif packet[:2] == b'\x55\x8b' and len(packet) >= 4:
                self.function_status = list(packet[2:4])
            elif packet[:2] == b'\x55\x83' and self.last_command:
                if self.last_command['hex'][4:] == packet.hex()[4:]:
                    self.last_command['notification_received'] = True

        await client.start_notify(notifier, receive)
        if self.client is not client or not client.is_connected:
            return
        self.notify_client = client
        self.log('电量／状态回传已开启。')

    def dispatch(self, packet, label, remember=True):
        client = self.client
        if not client or not client.is_connected:
            raise RuntimeError('未连接，请由用户手动连接。')
        if not self.selected or self.selected['name'] != NAME:
            raise RuntimeError('此控制工具只支持Master Remote Vibrator。')
        if self.writer is None:
            raise RuntimeError('尚未找到已核实的FFE2写入特征。')
        record = dict(label=label, hex=packet.hex(), queued=True, submitted=False,
                      periodic=False, write_ack=False, notification_received=False,
                      accepted_at=datetime.now().isoformat())
        item = (packet, record, time.perf_counter())
        if remember:
            self.last_command = record
        if packet == STOP:
            self.clear_waiting('被STOP清除')
            if self.inflight_is_query and self.inflight_task and not self.inflight_task.done():
                self.inflight_task.cancel()
                self.log('STOP抢占：取消在途查询等待')
            self.pending_stop = item
            self.last_control_clock = time.perf_counter()
        elif packet[:2] == b'\x55\x03':
            self.last_control_clock = time.perf_counter()
            if remember:
                if self.pending_target:
                    self.finish_waiting(self.pending_target, '被最新自由强度覆盖')
                self.pending_target = item
            else:
                self.mode_queue.append(item)
        else:
            if packet in self.query_queue:
                self.finish_waiting(self.query_queue[packet], '被同类查询合并')
            self.query_queue[packet] = item
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self.drain_writes(client, self.writer))
        return record

    def finish_waiting(self, item, reason):
        record = item[1]
        record.update(queued=False, discarded=reason)
        save('web-command', record)

    def clear_waiting(self, reason):
        for item in (self.pending_target, self.pending_stop):
            if item:
                self.finish_waiting(item, reason)
        for item in self.mode_queue:
            self.finish_waiting(item, reason)
        for item in self.query_queue.values():
            self.finish_waiting(item, reason)
        self.pending_target = self.pending_stop = None
        self.mode_queue.clear()
        self.query_queue.clear()

    def next_write(self):
        if self.pending_stop:
            item, self.pending_stop = self.pending_stop, None
            return item
        if self.pending_target:
            item, self.pending_target = self.pending_target, None
            return item
        if self.mode_queue:
            return self.mode_queue.popleft()
        if self.query_queue:
            key = next(iter(self.query_queue))
            return self.query_queue.pop(key)
        return None

    async def drain_writes(self, client, writer):
        try:
            while client is self.client and client.is_connected:
                item = self.next_write()
                if item is None:
                    return
                packet, record, accepted_clock = item
                record.update(queued=False, submitted=True,
                              submitted_at=datetime.now().isoformat(),
                              queue_elapsed_ms=round((time.perf_counter() - accepted_clock) * 1000, 1))
                started = time.perf_counter()
                is_control = (packet == STOP) or (packet[:2] == b'\x55\x03')
                is_query = not is_control
                timeout = 1.0 if is_query else 1.5
                self.inflight_control = is_control
                self.inflight_is_query = is_query
                self.log(f'提交{record["label"]}：{packet.hex(" ")}')

                async def do_write():
                    await client.write_gatt_char(writer, packet, response=True)

                write_task = asyncio.create_task(do_write())
                self.inflight_task = write_task
                self.pending.add(write_task)
                try:
                    await asyncio.wait_for(write_task, timeout=timeout)
                    record['write_ack'] = True
                except asyncio.TimeoutError:
                    record['error'] = f'底层写入超时({timeout}s)'
                    self.log(f'{record["label"]}底层写入超时({timeout}s)，已跳过防止阻塞后续指令')
                except asyncio.CancelledError:
                    record['error'] = '被高优先级指令中断取消'
                    self.log(f'{record["label"]}已被取消，让位紧急指令')
                except Exception as exc:
                    record['error'] = str(exc) or type(exc).__name__
                finally:
                    self.pending.discard(write_task)
                    self.inflight_task = None
                    self.inflight_is_query = False
                    if client is self.client:
                        self.inflight_control = False
                        if is_control:
                            self.last_control_clock = time.perf_counter()
                    record['write_elapsed_ms'] = round((time.perf_counter() - started) * 1000, 1)
                    outcome = '失败：' + record['error'] if record.get('error') else '成功'
                    self.log(f'{record["label"]}写入回调{outcome}：{record["write_elapsed_ms"]}ms。')
                    save('web-command', record)
        finally:
            if self.worker is asyncio.current_task():
                self.worker = None


bridge = Bridge()
loop = asyncio.new_event_loop()


def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type='application/json; charset=utf-8'):
        raw = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def allowed_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{PORT}'

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403, '{}')
        if self.path == '/':
            return self.send(200, (ROOT / 'panel.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN), 'text/html; charset=utf-8')
        self.send(404, '{}')

    def do_POST(self):
        if (not self.allowed_host() or self.headers.get('X-BLE-Token') != TOKEN
                or self.headers.get('Origin') not in (None, f'http://127.0.0.1:{PORT}')):
            return self.send(403, json.dumps(dict(error='请求被拒绝。')))
        command = self.path.removeprefix('/api/')
        if self.path not in ['/api/' + c for c in ('state', 'scan', 'scan-stop', 'connect', 'disconnect', 'battery', 'function-status', 'intensity', 'stop', 'play-mode', 'pause-mode', 'resume-mode', 'speed')]:
            return self.send(404, '{}')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 2048:
                raise ValueError('请求过大。')
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data, dict):
                raise ValueError('请求格式错误。')
            future = asyncio.run_coroutine_threadsafe(bridge.action(command, data), loop)
            result = future.result(timeout=55)
            self.send(200, json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            self.send(400, json.dumps(dict(error=str(exc) or type(exc).__name__), ensure_ascii=False))

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    import sys
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=run_loop, daemon=True).start()
    print(f'蓝牙面板：http://127.0.0.1:{PORT} ；关闭窗口或 Ctrl+C 停止。', flush=True)
    if '--no-browser' not in sys.argv:
        webbrowser.open(f'http://127.0.0.1:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            asyncio.run_coroutine_threadsafe(bridge.action('disconnect', {}), loop).result(timeout=12)
        finally:
            server.server_close()
            loop.call_soon_threadsafe(loop.stop)
