"""内部随机身份；供应商协议标识、摘要与整数序号不使用此模块。"""
import secrets
import string
from threading import RLock

ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits
_issued = set()
_lock = RLock()


def new_id(exists=None):
    """16 位安全随机 Base62，支持存储层传入碰撞检测。"""
    while True:
        raw = ''.join(secrets.choice(ALPHABET) for _ in range(16))
        value = '-'.join(raw[i:i + 4] for i in range(0, 16, 4))
        with _lock:
            if value in _issued:
                continue
            if exists is None or not exists(value):
                _issued.add(value)
                return value


def valid_id(value):
    return (isinstance(value, str) and len(value) == 19
            and all(value[i] == '-' for i in (4, 9, 14))
            and all(c in ALPHABET for i, c in enumerate(value) if i not in (4, 9, 14)))
