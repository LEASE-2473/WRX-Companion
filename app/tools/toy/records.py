"""设备运行记录写入主应用私有数据目录。"""
from datetime import datetime
import json
from pathlib import Path

RECORDS = Path(__file__).resolve().parents[3] / "data" / "toy" / "records"


def save(kind, value):
    RECORDS.mkdir(parents=True, exist_ok=True)
    path = RECORDS / f"{kind}-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"记录: {path}", flush=True)
