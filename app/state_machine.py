"""本地心理状态：仅基于真实时间与消息，不推断用户在线或现实活动。"""
from datetime import datetime
from math import sin, pi, exp
from random import gauss
from zoneinfo import ZoneInfo


def calculate(conversation, previous=None, now=None, noise=None):
    from .companion_store import utcnow
    now = now or utcnow()
    previous = previous or {}
    users = [m for m in conversation.messages if m.role == 'user' and m.timestamp]
    last = users[-1].timestamp if users else None
    # 新会话无互动时不凭空制造思念、担忧或主动联系。
    anchor = last or conversation.created_at
    reset = previous.get('released_at')
    if reset and datetime.fromisoformat(reset) > datetime.fromisoformat(anchor):
        anchor = reset
    hours = max(0, (now - datetime.fromisoformat(anchor)).total_seconds() / 3600)
    released = anchor == reset and reset is not None
    longing = min(100, max(0, (10 if released else 0) + 100 / (1 + exp(-(min(hours, 100) - 6) / 1.7)) - 2.85)) if last else 0
    local = now.astimezone(ZoneInfo(conversation.timezone))
    hour = local.hour + local.minute / 60
    energy = 50 + 40 * sin(2 * pi * (hour - 8) / 24)
    elapsed = max(0, (now - datetime.fromisoformat(last)).total_seconds()) if last else None
    worry = 90 if not released and 1 <= hour < 5 and elapsed is not None and elapsed < 1800 else 0
    # 读取 UI 不改变随机过程；每一分钟至多一个本地随机步。
    slot = int(now.timestamp() // 60)
    jitter = previous.get('noise', 0)
    if previous.get('slot') != slot:
        jitter = max(-10, min(10, jitter * .8 + (gauss(0, 2) if noise is None else noise)))
    desire = max(0, min(100, max(longing * (.75 + energy / 400), worry) + jitter)) if last else 0
    threshold = 75
    mood = '担心你熬夜' if worry else '想念' if longing >= 60 else '困倦' if energy < 25 else '平稳'
    reason = '近期有深夜聊天，担忧达到阈值' if worry else '距离上次互动较久，思念达到阈值' if desire >= threshold else '状态尚未达到主动联系阈值'
    return {**previous, 'character_id': conversation.character_id, 'conversation_id': conversation.id,
            'longing': round(longing, 1), 'worry': worry, 'energy': round(energy, 1),
            'noise': round(jitter, 2), 'desire_to_act': round(desire, 1), 'threshold': threshold,
            'mood': mood, 'reason': reason, 'last_user_message_at': last,
            'updated_at': now.isoformat(), 'slot': slot}


def prompt(state):
    return ('[当前内在状态（本地模拟数值，非真实情绪或用户在线检测）] ' +
            f"心情：{state['mood']}；思念 {state['longing']}/100；担忧 {state['worry']}/100；精力 {state['energy']}/100。"
            '仅根据聊天中明确的信息自然表达，尊重角色设定；不要报数值、机械问候或声称知道用户正在做什么。'
            '担忧不代表必须催促或指责，允许安静陪伴。')
