from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
import base64
import binascii

def validate_images(images):
    for url in images:
        header, sep, encoded = url.partition(',')
        if not sep or header not in {'data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64', 'data:image/gif;base64'}:
            raise ValueError('只支持 PNG、JPEG、WebP、GIF 图片')
        if len(encoded) > 7_000_000:
            raise ValueError('每张图片最多 5 MB')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('图片编码无效') from exc
        if not raw or len(raw) > 5 * 1024 * 1024:
            raise ValueError('每张图片必须非空且不超过 5 MB')
        valid = {'data:image/png;base64': raw.startswith(b'\x89PNG\r\n\x1a\n'),
                 'data:image/jpeg;base64': raw.startswith(b'\xff\xd8\xff'),
                 'data:image/gif;base64': raw[:6] in (b'GIF87a', b'GIF89a'),
                 'data:image/webp;base64': raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'}
        if not valid[header]:
            raise ValueError('图片格式与内容不匹配')
    return images


class ChatMessage(BaseModel):
    role: str
    content: str
    images: list[str] = Field(default_factory=list, max_length=4)
    _validate_images = field_validator('images')(validate_images)

    def api_message(self):
        content = self.content
        if self.images:
            content = ([{'type': 'text', 'text': content}] if content else []) + [
                {'type': 'image_url', 'image_url': {'url': url}} for url in self.images]
        return {'role': self.role, 'content': content}

class TokenUsage(BaseModel):
    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None

class StoredMessage(ChatMessage):
    id: str
    timestamp: str
    timezone: str = "Asia/Shanghai"
    local_datetime: str
    source: str = "web"
    request_id: str | None = None
    usage: TokenUsage | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)

class Character(BaseModel):
    id: str = ""
    name: str = Field(default="新角色", min_length=1, max_length=100)
    personality: str = ""
    background: str = ""
    relationship: str = ""
    speaking_style: str = ""
    system_prompt: str = ""
    persona: str = ""
    user_name: str = "用户"
    preset_id: str | None = None
    lorebook_id: str | None = None
    llm_profile_id: str | None = None
    tts_profile_id: str | None = None

class MessageBranch(BaseModel):
    action: Literal["branch", "edit", "regenerate"] = "branch"
    content: str | None = Field(default=None, min_length=1, max_length=100000)

class MessageSpeech(BaseModel):
    profile_id: str | None = None

class HeartbeatSettings(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=30, ge=1, le=1440)
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    max_messages_per_day: int = Field(default=6, ge=1, le=100)
    quiet_enabled: bool = False
    quiet_start: int = Field(default=23, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)

class SearchSettings(BaseModel):
    enabled: bool = False
    provider: Literal["tavily", "searxng", "volcengine", "custom"] = "tavily"
    endpoint: str = "https://api.tavily.com/search"
    api_key: str = ""
    max_results: int = Field(default=5, ge=1, le=10)
    search_depth: Literal["basic", "advanced"] = "basic"
    request_method: Literal["GET", "POST"] = "POST"
    request_template: dict = Field(default_factory=lambda: {"query": "{{query}}", "max_results": "{{max_results}}"})
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    results_path: str = "results"
    title_path: str = "title"
    url_path: str = "url"
    content_path: str = "content"
    extra_body: dict = Field(default_factory=dict)


class ConversationCreate(BaseModel):
    character_id: str = "default"
    name: str = ""
    timezone: str = "Asia/Shanghai"

class TextTurn(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    content: str = Field(default='', max_length=100000)
    images: list[str] = Field(default_factory=list, max_length=4)
    _validate_images = field_validator('images')(validate_images)
    timezone: str = "Asia/Shanghai"
    search_mode: Literal["AUTO", "ON", "OFF"] = "AUTO"

class ConversationRecord(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    messages: list[StoredMessage] = Field(default_factory=list)
    character_id: str = "default"
    timezone: str = "Asia/Shanghai"
    heartbeat: HeartbeatSettings = Field(default_factory=HeartbeatSettings)
    next_heartbeat_at: str | None = None
    pending_request_id: str | None = None
    parent_conversation_id: str | None = None
    branch_message_id: str | None = None

class ConversationUpdate(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)

PromptRole = Literal["system", "user", "assistant"]
InjectionPosition = Literal["relative", "in_chat"]
LoreCategory = Literal["char", "user", "world", "mechanism", "other"]
LorePosition = Literal["before_char", "after_char", "at_depth"]
MarkerIdentifier = Literal[
    "worldInfoBefore",
    "charDefinitions",
    "worldInfoAfter",
    "userDefinitions",
    "chatHistory",
]
LoreOutletIdentifier = Literal[
    "worldInfoBefore",
    "charDefinitions",
    "worldInfoAfter",
    "userDefinitions",
]

class PromptEntry(BaseModel):
    identifier: str
    name: str
    enabled: bool = True
    role: PromptRole = "system"
    content: str = ""
    injection_position: InjectionPosition = "relative"
    injection_depth: int = Field(default=0, ge=0)
    injection_order: int = 100
    marker: bool = False
    raw_fields: dict[str, Any] = Field(default_factory=dict)

class PromptOrderEntry(BaseModel):
    identifier: str
    enabled: bool = True
    raw_fields: dict[str, Any] = Field(default_factory=dict)

class PromptPreset(BaseModel):
    schema_version: int = 1
    id: str
    name: str
    prompts: list[PromptEntry] = Field(default_factory=list)
    prompt_order: list[PromptOrderEntry] = Field(default_factory=list)
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    raw_fields: dict[str, Any] = Field(default_factory=dict)

class PromptPresetsState(BaseModel):
    schema_version: int = 1
    presets: list[PromptPreset] = Field(default_factory=list)
    active_preset_id: str | None = None

class PromptPresetActiveUpdate(BaseModel):
    preset_id: str

class LorebookEntry(BaseModel):
    id: str
    title: str
    enabled: bool = True
    category: LoreCategory = "other"
    content: str = ""
    constant: bool = False
    keys: list[str] = Field(default_factory=list)
    scan_depth: int = Field(default=20, ge=0)
    position: LorePosition = "after_char"
    depth: int = Field(default=0, ge=0)
    role: PromptRole = "system"
    order: int = 100
    comment: str = ""
    outlet: LoreOutletIdentifier | None = None
    raw_fields: dict[str, Any] = Field(default_factory=dict)

class Lorebook(BaseModel):
    schema_version: int = 1
    id: str
    name: str
    entries: list[LorebookEntry] = Field(default_factory=list)
    raw_fields: dict[str, Any] = Field(default_factory=dict)

class LorebooksState(BaseModel):
    schema_version: int = 1
    lorebooks: list[Lorebook] = Field(default_factory=list)
    active_lorebook_id: str | None = None

class LorebookActiveUpdate(BaseModel):
    lorebook_id: str

class RuntimeSettings(BaseModel):
    schema_version: int = 1
    history_depth: int = Field(default=20, ge=0)

class VectorMemoryConfig(BaseModel):
    enabled: bool = False
    api_url: str = ""
    api_key: str = ""
    model: str = "BAAI/bge-m3"
    threshold: float = Field(default=0.3, ge=-1, le=1)
    max_results: int = Field(default=8, ge=1, le=50)
    context_depth: int = Field(default=2, ge=1, le=5)
    separator: str = "---"
    rerank_enabled: bool = False
    rerank_url: str = "https://api.siliconflow.cn/v1/rerank"
    rerank_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

class VectorChunk(BaseModel):
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_sha256: str = ""
    vector: list[float] | None = None

class VectorLibrary(BaseModel):
    id: str
    name: str
    enabled: bool = True
    source_format: str = "text"
    chunks: list[VectorChunk] = Field(default_factory=list)

class VectorMemoryState(BaseModel):
    schema_version: int = 1
    config: VectorMemoryConfig = Field(default_factory=VectorMemoryConfig)
    libraries: list[VectorLibrary] = Field(default_factory=list)

class SttProviderProfile(BaseModel):
    id: str
    name: str
    provider_type: str = "volcengine"
    api_key: str = ""
    endpoint: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
    stream_endpoint: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    resource_id: str = ""
    stream_two_pass: bool = True

class LlmProviderProfile(BaseModel):
    id: str
    name: str
    provider_type: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""

class TtsProviderProfile(BaseModel):
    id: str
    name: str
    provider_type: str = "http"
    endpoint: str = ""
    resource_id: str = ""
    api_key: str = ""
    voice_type: str = ""
    request_template: dict = Field(default_factory=dict)
    emotion: str = ""
    enable_emotion: bool = False
    emotion_scale: float = 4.0
    speed_ratio: float = 1.0

class ProviderProfilesState(BaseModel):
    schema_version: int = 1
    stt_profiles: list[SttProviderProfile] = Field(default_factory=list)
    llm_profiles: list[LlmProviderProfile] = Field(default_factory=list)
    tts_profiles: list[TtsProviderProfile] = Field(default_factory=list)
    active_stt_profile_id: str | None = None
    active_llm_profile_id: str | None = None
    active_tts_profile_id: str | None = None

class ProviderActiveUpdate(BaseModel):
    profile_id: str

class SettingsResponse(BaseModel):
    version: str
    mode: str
    prompt_presets: PromptPresetsState
    lorebooks: LorebooksState
    runtime_settings: RuntimeSettings
    provider_profiles: dict[str, Any] = Field(default_factory=dict)
    provider_info: dict[str, str] = Field(default_factory=dict)
    vector_memory: dict[str, Any] = Field(default_factory=dict)

class ProcessRequest(BaseModel):
    conversation_id: str = ""
    request_id: str = ""
    timezone: str = "Asia/Shanghai"
    search_mode: Literal["AUTO", "ON", "OFF"] = "AUTO"
    audio_base64: str = ""
    transcript: str = ""
    stt_latency: float = 0.0
    recording_duration: float = 0.0
    messages: list[ChatMessage] = Field(default_factory=list)
    provider_snapshot_id: str = ""
