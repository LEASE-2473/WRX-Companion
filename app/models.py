from typing import Any, Literal

from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str
    content: str

class ConversationRecord(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage] = Field(default_factory=list)

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

class ProcessRequest(BaseModel):
    audio_base64: str = ""
    transcript: str = ""
    stt_latency: float = 0.0
    recording_duration: float = 0.0
    messages: list[ChatMessage] = Field(default_factory=list)
    provider_snapshot_id: str = ""
