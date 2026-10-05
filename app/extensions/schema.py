from pathlib import Path
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Invocation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tag: str
    endpoint: str = '/api/invoke'
    read_only_actions: list[str] = Field(default_factory=list)

    @field_validator('tag')
    @classmethod
    def valid_tag(cls, value):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value) or value in {'app_call', 'emotion_update'}:
            raise ValueError('调用标签需为唯一的小写英文／数字／下划线，不能使用宿主标签')
        return value

    @field_validator('endpoint')
    @classmethod
    def valid_endpoint(cls, value):
        if not value.startswith('/') or value.startswith('//') or any(x in value for x in ('..', '?', '#', '\\')):
            raise ValueError('调用端点必须是扩展内绝对路径')
        return value


class ExtensionManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: int = 1
    id: str
    name: str = Field(min_length=1, max_length=100)
    icon: str = '🧩'
    version: str = '1.0.0'
    description: str = ''
    entry_cmd: list[str] = Field(min_length=1, max_length=20)
    internal_port: int = Field(ge=1024, le=65535)
    has_panel: bool = True
    skill_path: str = 'SKILL.md'
    invocation: Invocation
    shutdown_path: str = '/api/shutdown'

    @field_validator('id')
    @classmethod
    def valid_id(cls, value):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', value):
            raise ValueError('扩展 ID 格式错误')
        return value

    @field_validator('schema_version')
    @classmethod
    def version_supported(cls, value):
        if value != 1: raise ValueError('不支持的契约版本')
        return value

    @field_validator('shutdown_path')
    @classmethod
    def shutdown_endpoint(cls, value):
        return Invocation.valid_endpoint(value)


def local_file(directory: Path, value: str):
    path = (directory / value).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError('声明文件不存在或越过扩展目录')
    return path
