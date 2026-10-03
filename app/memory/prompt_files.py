"""统一Markdown提示词读取／保存；不缓存，不回退到数据库中的旧文本。"""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from app.config import APP_DIR

PROMPT_DIR = APP_DIR / 'memory' / 'prompts'
NAMES = frozenset({'diary','diary_instant','diary_merge','activity','event',
                   'system','emotion_summary'})

def path(name):
    if name not in NAMES:
        raise ValueError('未知记忆提示词名称')
    return PROMPT_DIR / (name+'.md')

def read(name):
    file=path(name)
    try:
        text=file.read_text(encoding='utf-8-sig').strip()
    except OSError as exc:
        raise ValueError(f'无法读取记忆提示词：{file}，请恢复该Markdown文件') from exc
    if not text:
        raise ValueError(f'记忆提示词为空：{file}')
    return text

def write(name,text):
    file=path(name)
    if not isinstance(text,str) or not text.strip():
        raise ValueError(f'提示词 {name} 不能为空')
    file.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with NamedTemporaryFile(mode='w',encoding='utf-8',dir=file.parent,delete=False,suffix='.tmp') as handle:
            temp=Path(handle.name)
            handle.write(text.strip()+'\n')
        os.replace(temp,file)
    finally:
        if temp and temp.exists(): temp.unlink()

def save_role(settings):
    for kind,preset in settings.presets.items():
        if not preset.prompt.strip():
            raise ValueError('完整记忆提示词不能为空')
    if not settings.presets['diary'].instant_prompt.strip():
        raise ValueError('即时日记提示词不能为空')
    for kind,preset in settings.presets.items():
        write(kind,preset.prompt)
    write('diary_instant',settings.presets['diary'].instant_prompt)
