"""技能配置缺失时使用默认值；仅管理操作落盘，不在聊天时创建文件。"""
import json
import threading
from app.config import DATA_DIR

FILE = DATA_DIR / 'skills_config.json'
_lock = threading.Lock()


def load():
    if not FILE.exists(): return {}
    value = json.loads(FILE.read_text(encoding='utf-8'))
    if not isinstance(value,dict): raise ValueError('技能配置必须是对象')
    return value


def policy(name):
    value = load().get(name, {'enabled':True,'injection':'always' if name == 'diary-write' else 'on_demand'})
    if not isinstance(value,dict) or type(value.get('enabled')) is not bool or value.get('injection') not in {'always','on_demand'}:
        raise ValueError('技能配置不合法')
    return value


def save(name, value):
    if set(value) != {'enabled','injection'} or type(value['enabled']) is not bool or value['injection'] not in {'always','on_demand'}:
        raise ValueError('技能配置不合法')
    with _lock:
        settings = load(); settings[name] = value
        FILE.parent.mkdir(parents=True,exist_ok=True)
        temp = FILE.with_suffix('.tmp'); temp.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(FILE)
