"""全局核心常驻与两轮用户关键词激活；不读取数据库或调用模型。"""

def context(value, current, history):
    previous_user = next((m.content for m in reversed(history) if m.role == 'user'), '')
    haystack = '\n'.join([previous_user, current]).casefold()
    selected = [e for e in value.entries if any(k.strip() and k.casefold() in haystack for k in e.keywords)]
    return '[全局用户资料｜背景资料]\n称呼：' + value.name + '\n核心信息：' + value.core + ''.join('\n[' + e.tag + ']\n' + e.content for e in selected)
