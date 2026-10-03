from pathlib import Path

APP_VERSION = "2.0.0-alpha"
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROVIDER_PROFILES_FILE = DATA_DIR / "provider_profiles.json"
WRX_PROMPT_PRESETS_FILE = DATA_DIR / "wrx_prompt_presets.json"
WRX_LOREBOOKS_FILE = DATA_DIR / "wrx_lorebooks.json"
WRX_RUNTIME_SETTINGS_FILE = DATA_DIR / "wrx_runtime_settings.json"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"
VECTOR_MEMORY_FILE = DATA_DIR / "vector_memory.json"

APP_DIR = ROOT / "app"
STATIC_DIR = APP_DIR / "static"
SKILL_DEFINITIONS_DIR = APP_DIR / "skills" / "definitions"
