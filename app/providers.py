import base64
import asyncio
import gzip
import json
import struct
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .models import ChatMessage, LlmProviderProfile, SttProviderProfile, TtsProviderProfile
from .provider_store import ProviderSnapshot

class ProviderError(RuntimeError):
    pass

_LLM_HTTP_CLIENT: httpx.AsyncClient | None = None
_TTS_HTTP_CLIENT: httpx.AsyncClient | None = None


def _input_token_usage(body: Any) -> int | None:
    """读取常见 OpenAI-compatible 输入 Token 字段；没有可靠值时返回 None。"""
    if not isinstance(body, dict):
        return None
    containers = [body.get("usage"), body.get("usage_metadata"), body.get("usageMetadata")]
    keys = (
        "prompt_tokens", "input_tokens", "promptTokens", "inputTokens",
        "prompt_token_count", "input_token_count", "promptTokenCount", "inputTokenCount",
    )
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, bool):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                return parsed
    return None

class SttProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str: ...

class LlmProvider(ABC):
    last_prompt_tokens: int | None = None

    @abstractmethod
    async def complete(self, messages: list[ChatMessage]) -> str: ...

    async def complete_with_metrics(self, messages: list[ChatMessage]) -> tuple[str, float | None]:
        return await self.complete(messages), None

    async def stream_complete(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        yield await self.complete(messages)

class TtsProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, preset: TtsProviderProfile) -> bytes: ...

    def supports_streaming_pcm(self, preset: TtsProviderProfile) -> bool:
        return False

    async def stream_pcm(self, texts: AsyncIterator[str], preset: TtsProviderProfile) -> AsyncIterator[bytes]:
        raise NotImplementedError

def _pack_header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes([(1 << 4) | 1, (message_type << 4) | flags, (serialization << 4) | compression, 0])

def _pack_message(header: bytes, payload: bytes, sequence: int | None = None) -> bytes:
    return header + struct.pack(">I", len(payload)) + payload

class VolcengineStt(SttProvider):
    def __init__(self, profile: SttProviderProfile) -> None:
        self.profile = profile.model_copy(deep=True)

    async def transcribe_stream(
        self,
        chunks: AsyncIterator[bytes],
        on_ready: Callable[[], Awaitable[None]] | None = None,
        on_partial: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """在用户按住 PTT 时实时上传 PCM，只把松键后的最终结果交给 LLM。"""
        profile = self.profile
        if not profile.api_key:
            raise ProviderError("缺少火山 STT API Key")
        headers = {
            "X-Api-Resource-Id": profile.resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Api-Sequence": "-1",
            "X-Api-Key": profile.api_key,
        }
        request = {
            "user": {"uid": "local-user"},
            "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_nonstream": profile.stream_two_pass,
                "show_utterances": True,
            },
        }
        compressed = gzip.compress(json.dumps(request, ensure_ascii=False).encode())
        endpoint = profile.stream_endpoint or "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
        async with websockets.connect(endpoint, additional_headers=headers) as ws:
            await ws.send(_pack_message(_pack_header(1, 0, 1, 1), compressed))
            if on_ready:
                await on_ready()

            async def send_audio() -> None:
                pending: bytes | None = None
                async for chunk in chunks:
                    if not chunk:
                        continue
                    if pending is not None:
                        await ws.send(_pack_message(_pack_header(2, 0, 0, 1), gzip.compress(pending)))
                    pending = chunk
                final_chunk = pending or b""
                await ws.send(_pack_message(_pack_header(2, 2, 0, 1), gzip.compress(final_chunk)))

            sender = asyncio.create_task(send_audio())
            final_text = ""
            try:
                while True:
                    if sender.done() and sender.exception() is not None:
                        raise sender.exception()
                    receive = asyncio.create_task(ws.recv())
                    watched = {receive} if sender.done() else {receive, sender}
                    done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
                    if sender in done and sender.exception() is not None:
                        receive.cancel()
                        raise sender.exception()
                    if receive not in done:
                        receive.cancel()
                        continue
                    message = receive.result()
                    data, text, is_final = _decode_stt_response(message)
                    if text:
                        final_text = text
                        if on_partial:
                            await on_partial(text)
                    if is_final:
                        break
                await sender
            except ConnectionClosed:
                pass
            finally:
                if not sender.done():
                    sender.cancel()
            return final_text

    async def transcribe(self, audio: bytes) -> str:
        profile = self.profile
        if not profile.api_key:
            raise ProviderError("缺少火山 STT API Key")
        headers = {
            "X-Api-Resource-Id": profile.resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Api-Sequence": "-1",
        }
        headers["X-Api-Key"] = profile.api_key
        request = {"user": {"uid": "local-user"}, "audio": {"format": "wav", "rate": 16000, "bits": 16, "channel": 1}, "request": {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True}}
        compressed = gzip.compress(json.dumps(request, ensure_ascii=False).encode())
        async with websockets.connect(profile.endpoint, additional_headers=headers) as ws:
            await ws.send(_pack_message(_pack_header(1, 0, 1, 1), compressed))
            chunk_size = 6400  # 16 kHz / 16-bit / mono 下约 200 ms，遵循官方建议。
            offsets = list(range(0, len(audio), chunk_size))
            for index, offset in enumerate(offsets):
                chunk = gzip.compress(audio[offset:offset + chunk_size])
                is_last = index == len(offsets) - 1
                # audio-only payload 是 raw bytes（serialization=0），末块真实音频直接标记为负包。
                await ws.send(_pack_message(_pack_header(2, 2 if is_last else 0, 0, 1), chunk))
            final_text = ""
            received_types: list[int] = []
            parsed_responses = 0
            try:
                async for message in ws:
                    if not isinstance(message, bytes) or len(message) < 12:
                        continue
                    message_type = message[1] >> 4
                    received_types.append(message_type)
                    flags = message[1] & 0x0F
                    if message_type == 15 and len(message) >= 12:
                        error_code = struct.unpack(">I", message[4:8])[0]
                        error_len = struct.unpack(">I", message[8:12])[0]
                        error_text = message[12:12 + error_len].decode(errors="replace")
                        raise ProviderError(f"火山 STT 返回错误 {error_code}：{error_text[:500]}")
                    offset = 4
                    if message_type == 9 and flags in (1, 3):
                        offset += 4
                    if len(message) < offset + 4:
                        continue
                    payload_len = struct.unpack(">I", message[offset:offset + 4])[0]
                    payload = message[offset + 4:offset + 4 + payload_len]
                    try:
                        if (message[2] & 0x0F) == 1:
                            payload = gzip.decompress(payload)
                        data = json.loads(payload.decode())
                    except Exception:
                        data = None
                        for candidate_offset in (4, 8, 12):
                            if len(message) < candidate_offset + 4:
                                continue
                            candidate_len = struct.unpack(">I", message[candidate_offset:candidate_offset + 4])[0]
                            candidate = message[candidate_offset + 4:candidate_offset + 4 + candidate_len]
                            try:
                                if (message[2] & 0x0F) == 1:
                                    candidate = gzip.decompress(candidate)
                                data = json.loads(candidate.decode())
                                break
                            except Exception:
                                pass
                        if data is None:
                            continue
                    parsed_responses += 1
                    payload_msg = data.get("payload_msg", data)
                    if isinstance(payload_msg, str):
                        try:
                            payload_msg = json.loads(payload_msg)
                        except json.JSONDecodeError:
                            payload_msg = {}
                    result = payload_msg.get("result", {}) if isinstance(payload_msg, dict) else {}
                    if isinstance(result, list):
                        texts = [item.get("text", "") for item in result if isinstance(item, dict)]
                        final_text = "".join(texts) or final_text
                        result = result[-1] if result else {}
                    if isinstance(result, dict):
                        final_text = result.get("text", final_text) or final_text
                        if not final_text:
                            for item in result.values():
                                if isinstance(item, dict) and isinstance(item.get("text"), str):
                                    final_text = item["text"]
                                    break
                    # definite 只代表某个分句确定，不代表整段录音完成；只接受协议末包信号。
                    if flags in (2, 3) or data.get("is_last_package"):
                        break
            except ConnectionClosed:
                pass
            if not final_text:
                if parsed_responses:
                    return ""
                raise ProviderError(f"火山 STT 未返回识别文本（收到消息类型：{received_types}）")
            return final_text

def _decode_stt_response(message: Any) -> tuple[dict[str, Any] | None, str, bool]:
    if not isinstance(message, bytes) or len(message) < 8:
        return None, "", False
    message_type = message[1] >> 4
    flags = message[1] & 0x0F
    if message_type == 15 and len(message) >= 12:
        error_code = struct.unpack(">I", message[4:8])[0]
        error_len = struct.unpack(">I", message[8:12])[0]
        error_text = message[12:12 + error_len].decode(errors="replace")
        raise ProviderError(f"火山 STT 返回错误 {error_code}：{error_text[:500]}")
    offset = 8 if message_type == 9 and flags in (1, 3) else 4
    data = None
    for candidate_offset in (offset, 4, 8, 12):
        if len(message) < candidate_offset + 4:
            continue
        payload_len = struct.unpack(">I", message[candidate_offset:candidate_offset + 4])[0]
        payload = message[candidate_offset + 4:candidate_offset + 4 + payload_len]
        try:
            if (message[2] & 0x0F) == 1:
                payload = gzip.decompress(payload)
            data = json.loads(payload.decode())
            break
        except Exception:
            continue
    if not isinstance(data, dict):
        return None, "", flags in (2, 3)
    payload_msg = data.get("payload_msg", data)
    if isinstance(payload_msg, str):
        try:
            payload_msg = json.loads(payload_msg)
        except json.JSONDecodeError:
            payload_msg = {}
    result = payload_msg.get("result", {}) if isinstance(payload_msg, dict) else {}
    text = ""
    if isinstance(result, list):
        text = "".join(item.get("text", "") for item in result if isinstance(item, dict))
    elif isinstance(result, dict):
        text = result.get("text", "") or ""
        if not text:
            for item in result.values():
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    text = item["text"]
                    break
    return data, text, flags in (2, 3) or bool(data.get("is_last_package"))

class OpenAICompatibleLlm(LlmProvider):
    def __init__(self, profile: LlmProviderProfile) -> None:
        self.profile = profile.model_copy(deep=True)
        self.last_prompt_tokens = None
        self.generation_parameters: dict[str, object] = {}
        self.generation_parameter_report: dict[str, object] = {"applied": {}, "ignored": {}}

    def set_generation_parameters(self, values: dict | None) -> None:
        source = values if isinstance(values, dict) else {}
        applied: dict[str, object] = {}
        ignored: dict[str, str] = {}

        def number(name: str, minimum: float, maximum: float) -> None:
            value = source.get(name)
            if value is None:
                return
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
                ignored[name] = f"必须是 {minimum} 至 {maximum} 的数字"
                return
            applied[name] = value

        number("temperature", 0, 2)
        number("top_p", 0, 1)
        number("frequency_penalty", -2, 2)
        number("presence_penalty", -2, 2)

        if "seed" in source:
            seed = source["seed"]
            if isinstance(seed, int) and not isinstance(seed, bool):
                applied["seed"] = seed
            else:
                ignored["seed"] = "必须是整数"

        max_tokens_source = "max_tokens" if "max_tokens" in source else "openai_max_tokens" if "openai_max_tokens" in source else None
        if max_tokens_source:
            max_tokens = source[max_tokens_source]
            if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0:
                applied["max_tokens"] = max_tokens
            else:
                ignored[max_tokens_source] = "必须是正整数"

        handled = {
            "temperature", "top_p", "frequency_penalty", "presence_penalty",
            "seed", "max_tokens", "openai_max_tokens",
        }
        for name in source:
            if name not in handled:
                ignored[name] = "不是当前 OpenAI-compatible 安全透传子集；仅保留在 Preset"

        self.generation_parameters = applied
        self.generation_parameter_report = {"applied": applied.copy(), "ignored": ignored}

    def client(self) -> httpx.AsyncClient:
        global _LLM_HTTP_CLIENT
        if _LLM_HTTP_CLIENT is None or _LLM_HTTP_CLIENT.is_closed:
            _LLM_HTTP_CLIENT = httpx.AsyncClient(timeout=90, limits=httpx.Limits(max_keepalive_connections=4, max_connections=8, keepalive_expiry=60))
        return _LLM_HTTP_CLIENT

    async def complete(self, messages: list[ChatMessage]) -> str:
        text, _ = await self.complete_with_metrics(messages)
        return text

    async def complete_with_metrics(self, messages: list[ChatMessage]) -> tuple[str, float | None]:
        import time
        profile = self.profile
        if not profile.api_key or not profile.model:
            raise ProviderError("缺少 LLM API Key 或 Model")
        payload = {"model": profile.model, "messages": [m.model_dump() for m in messages], **self.generation_parameters, "stream": True}
        client = self.client()
        first_token_at = None
        pieces: list[str] = []
        self.last_prompt_tokens = None
        async with client.stream("POST", f"{profile.base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {profile.api_key}"}, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    body = json.loads(data)
                    usage = _input_token_usage(body)
                    if usage is not None:
                        self.last_prompt_tokens = usage
                    delta = body.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                except (ValueError, IndexError, KeyError):
                    continue
                if delta and first_token_at is None:
                    first_token_at = time.perf_counter()
                pieces.append(delta)
        return "".join(pieces), first_token_at

    async def stream_complete(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        profile = self.profile
        if not profile.api_key or not profile.model:
            raise ProviderError("缺少 LLM API Key 或 Model")
        payload = {"model": profile.model, "messages": [m.model_dump() for m in messages], **self.generation_parameters, "stream": True}
        self.last_prompt_tokens = None
        emitted = False
        endpoint = f"{profile.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {profile.api_key}"}
        for attempt in range(2):
            try:
                async with self.client().stream("POST", endpoint, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            body = json.loads(data)
                        except (ValueError, IndexError, KeyError):
                            continue
                        error = body.get("error") if isinstance(body, dict) else None
                        if error:
                            detail = error.get("message") if isinstance(error, dict) else str(error)
                            raise ProviderError(f"LLM 返回错误：{detail or '未知错误'}")
                        usage = _input_token_usage(body)
                        if usage is not None:
                            self.last_prompt_tokens = usage
                        try:
                            choice = body.get("choices", [{}])[0]
                            delta = choice.get("delta", {}).get("content") or choice.get("message", {}).get("content") or ""
                        except (AttributeError, IndexError, KeyError):
                            continue
                        if isinstance(delta, list):
                            delta = "".join(str(part.get("text") or part.get("content") or "") for part in delta if isinstance(part, dict))
                        if delta:
                            emitted = True
                            yield delta
                break
            except httpx.TransportError:
                # 只在还没有输出正文时重试，避免已经交给 TTS 的半段回复被重复发送。
                if emitted or attempt >= 1:
                    raise
                await asyncio.sleep(0.3)
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code in {408, 429, 500, 502, 503, 504}
                if emitted or attempt >= 1 or not retryable:
                    raise
                await asyncio.sleep(0.3)
        if emitted:
            return

        # 部分 OpenAI-compatible 聚合服务会偶发以 200 + [DONE] 结束，却不返回正文。
        # 使用同一模型、同一 messages 做一次非流式兜底，不改变模型或回复参数。
        fallback_payload = {**payload, "stream": False}
        response = await self.client().post(endpoint, headers=headers, json=fallback_payload)
        response.raise_for_status()
        body = response.json()
        usage = _input_token_usage(body)
        if usage is not None:
            self.last_prompt_tokens = usage
        error = body.get("error") if isinstance(body, dict) else None
        if error:
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise ProviderError(f"LLM 返回错误：{detail or '未知错误'}")
        try:
            content = body.get("choices", [{}])[0].get("message", {}).get("content") or ""
        except (AttributeError, IndexError, KeyError):
            content = ""
        if isinstance(content, list):
            content = "".join(str(part.get("text") or part.get("content") or "") for part in content if isinstance(part, dict))
        if not str(content).strip():
            raise ProviderError("LLM 未返回正文；已使用同一模型重试一次")
        yield str(content)

class HttpTts(TtsProvider):
    def supports_streaming_pcm(self, preset: TtsProviderProfile) -> bool:
        return preset.endpoint.startswith("wss://")

    async def stream_pcm(self, texts: AsyncIterator[str], preset: TtsProviderProfile) -> AsyncIterator[bytes]:
        async for chunk in stream_doubao_websocket(texts, preset, preset.api_key):
            yield chunk

    async def synthesize(self, text: str, preset: TtsProviderProfile) -> bytes:
        if not preset.endpoint:
            raise ProviderError("当前 TTS 预设没有 endpoint")
        if preset.endpoint.startswith("wss://"):
            return await synthesize_doubao_websocket(text, preset, preset.api_key)
        body = dict(preset.request_template)
        body.setdefault("text", text)
        if preset.voice_type:
            body.setdefault("voice_type", preset.voice_type)
        headers = {"Content-Type": "application/json"}
        if preset.api_key:
            headers["Authorization"] = f"Bearer {preset.api_key}"
        global _TTS_HTTP_CLIENT
        if _TTS_HTTP_CLIENT is None or _TTS_HTTP_CLIENT.is_closed:
            _TTS_HTTP_CLIENT = httpx.AsyncClient(timeout=90, limits=httpx.Limits(max_keepalive_connections=4, max_connections=8, keepalive_expiry=60))
        response = await _TTS_HTTP_CLIENT.post(preset.endpoint, headers=headers, json=body)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "audio" in content_type:
            return response.content
        payload: Any = response.json()
        encoded = payload.get("data") or payload.get("audio") or payload.get("audio_base64")
        if not encoded:
            raise ProviderError("TTS 响应未找到音频数据，请检查预设 request_template")
        return base64.b64decode(encoded)

async def synthesize_doubao_websocket(text: str, preset: TtsProviderProfile, api_key: str) -> bytes:
    async def texts() -> AsyncIterator[str]:
        yield text

    audio = bytearray()
    async for chunk in stream_doubao_websocket(texts(), preset, api_key):
        audio.extend(chunk)
    if not audio:
        raise ProviderError("火山 TTS 未返回音频")
    return wav_from_pcm(bytes(audio), 24000)

async def stream_doubao_websocket(texts: AsyncIterator[str], preset: TtsProviderProfile, api_key: str) -> AsyncIterator[bytes]:
    if not api_key:
        raise ProviderError("当前 TTS Profile 缺少 API Key")
    if not preset.voice_type:
        raise ProviderError("当前 TTS Profile 缺少 Voice Type，请填写火山音色库中的 speaker ID")
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": preset.resource_id or "seed-tts-2.0",
        "X-Api-Connect-Id": str(uuid.uuid4()),
        "X-Api-Request-Id": str(uuid.uuid4()),
    }
    session_id = str(uuid.uuid4())

    def request_frame(event: int, payload: dict, session: str | None = None) -> bytes:
        header = bytes.fromhex("11141000")
        event_bytes = struct.pack(">I", event)
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode()
        parts = [header, event_bytes]
        if session is not None:
            session_bytes = session.encode()
            parts.extend([struct.pack(">I", len(session_bytes)), session_bytes])
        parts.extend([struct.pack(">I", len(payload_bytes)), payload_bytes])
        return b"".join(parts)

    def parse_event(message: bytes) -> tuple[int, str | None, bytes | dict | None]:
        if len(message) < 8:
            raise ProviderError("TTS 返回帧长度不足")
        message_type = message[1]
        event = struct.unpack(">I", message[4:8])[0]
        if message_type == 0xB4:
            offset = 8
            session_len = struct.unpack(">I", message[offset:offset + 4])[0]
            offset += 4
            session = message[offset:offset + session_len].decode()
            offset += session_len
            audio_len = struct.unpack(">I", message[offset:offset + 4])[0]
            offset += 4
            return event, session, message[offset:offset + audio_len]
        if message_type == 0x94 and event > 52:
            offset = 8
            session_len = struct.unpack(">I", message[offset:offset + 4])[0]
            offset += 4
            session = message[offset:offset + session_len].decode()
            offset += session_len
            payload_len = struct.unpack(">I", message[offset:offset + 4])[0]
            offset += 4
            payload = json.loads(message[offset:offset + payload_len].decode() or "{}")
            return event, session, payload
        if message_type == 0xF0:
            error_len = struct.unpack(">I", message[8:12])[0]
            raise ProviderError(f"火山 TTS 返回错误：{message[12:12 + error_len].decode(errors='replace')}")
        return event, None, None

    req_params = {"speaker": preset.voice_type, "audio_params": {"format": "pcm", "sample_rate": 24000}}
    req_params.update(preset.request_template.get("req_params", {}))
    req_params["speaker"] = preset.voice_type
    if preset.enable_emotion and preset.emotion:
        req_params["emotion"] = preset.emotion
        req_params["enable_emotion"] = True
        req_params["emotion_scale"] = max(1.0, min(5.0, preset.emotion_scale))
    if preset.speed_ratio != 1.0:
        req_params["audio_params"]["speed_ratio"] = max(0.1, min(2.0, preset.speed_ratio))
    async with websockets.connect(preset.endpoint, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        await ws.send(request_frame(1, {}))
        while True:
            event, _, _ = parse_event(await ws.recv())
            if event == 50:
                break
        await ws.send(request_frame(100, {"namespace": "BidirectionalTTS", "event": 100, "req_params": req_params}, session_id))
        while True:
            event, _, _ = parse_event(await ws.recv())
            if event == 150:
                break
        async def send_text() -> None:
            async for text in texts:
                if text.strip():
                    await ws.send(request_frame(200, {"namespace": "BidirectionalTTS", "event": 200, "req_params": {**req_params, "text": text}}, session_id))
            await ws.send(request_frame(102, {"namespace": "BidirectionalTTS", "event": 102}, session_id))

        sender = asyncio.create_task(send_text())
        while True:
            try:
                event, _, payload = parse_event(await ws.recv())
                if isinstance(payload, bytes) and payload:
                    yield payload
                if event == 152:
                    break
            finally:
                if sender.done() and sender.exception() is not None:
                    raise sender.exception()
        await sender
        await ws.send(request_frame(2, {}))

def wav_from_pcm(pcm: bytes, rate: int) -> bytes:
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm))
    return header + pcm

def make_wav_tone(frequency: float, seconds: float, rate: int = 16000) -> bytes:
    import math
    frames = bytearray()
    for i in range(int(rate * seconds)):
        sample = int(12000 * math.sin(2 * math.pi * frequency * i / rate))
        frames.extend(struct.pack("<h", sample))
    header = b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(frames))
    return header + frames

def get_providers(snapshot: ProviderSnapshot) -> tuple[SttProvider, LlmProvider, TtsProvider]:
    return VolcengineStt(snapshot.stt), OpenAICompatibleLlm(snapshot.llm), HttpTts()


async def fetch_llm_models(profile: LlmProviderProfile) -> list[str]:
    if not profile.base_url or not profile.api_key:
        raise ProviderError("LLM Base URL 和 API Key 不能为空")
    response = await OpenAICompatibleLlm(profile).client().get(
        f"{profile.base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {profile.api_key}"},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    models = sorted({str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")})
    if not models:
        raise ProviderError("/models 请求成功，但没有返回可用模型 ID")
    return models


async def test_llm_stream(profile: LlmProviderProfile) -> str:
    if not profile.base_url or not profile.api_key or not profile.model:
        raise ProviderError("LLM Base URL、API Key 和 Model 均不能为空")
    llm = OpenAICompatibleLlm(profile)
    payload = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "只回复：连接成功"}],
        "stream": True,
    }
    async with llm.client().stream(
        "POST",
        f"{profile.base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {profile.api_key}"},
        json=payload,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                body = json.loads(data)
                choice = body.get("choices", [{}])[0]
                delta = choice.get("delta", {}).get("content") or ""
            except (AttributeError, IndexError, KeyError, ValueError):
                continue
            if isinstance(delta, list):
                delta = "".join(str(part.get("text") or part.get("content") or "") for part in delta if isinstance(part, dict))
            if str(delta).strip():
                return str(delta)
    raise ProviderError("HTTP 请求成功，但没有收到流式正文增量")


async def test_stt_real_request(profile: SttProviderProfile) -> str:
    return await VolcengineStt(profile).transcribe(make_wav_tone(0, 0.3))


async def test_tts_real_request(profile: TtsProviderProfile) -> bytes:
    audio = await HttpTts().synthesize("你好，这是 WRX 语音连接测试。", profile)
    if not audio:
        raise ProviderError("TTS 请求成功，但没有返回音频")
    return audio
