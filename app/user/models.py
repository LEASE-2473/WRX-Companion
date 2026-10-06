"""全局用户资料与标签的验证模型。"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.user.prompt_files import PROMPT

class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tag: str = Field(min_length=1, max_length=80)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    content: str = Field(min_length=1, max_length=12000)

    @field_validator('tag', 'content')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('标签和总结不能为空')
        return value.strip()

    @field_validator('keywords')
    @classmethod
    def clean_keywords(cls, values):
        if any(not v.strip() or len(v) > 100 for v in values):
            raise ValueError('关键词需要1–100字')
        return list(dict.fromkeys(v.strip() for v in values))


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(default='用户', min_length=1, max_length=100)
    core: str = Field(default='', max_length=30000)
    entries: list[Entry] = Field(default_factory=list, max_length=200)
    summary_enabled: bool = False
    llm_profile_id: str | None = None
    summary_hour: int = Field(default=3, ge=0, le=23)
    summary_prompt: str = Field(default=PROMPT, min_length=1, max_length=30000)
    revision: int = 0


class ProfileImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    core: str = Field(max_length=30000)
    entries: list[Entry] = Field(max_length=200)
    revision: int
