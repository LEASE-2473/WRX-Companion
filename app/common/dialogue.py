"""供后台任务共享的纯对话正文清理，不承载记忆业务。"""
import re

def plain_dialogue(text):
    text = re.sub(r'<(?:emotion_update|app_call)\b[^>]*>.*?</(?:emotion_update|app_call)>', '', text, flags=re.S)
    text = re.sub(r'<(?:emotion_update|app_call)\b.*$', '', text, flags=re.S)
    return re.sub(r'!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>', '', text, flags=re.I).strip()
