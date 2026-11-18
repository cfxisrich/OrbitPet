import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from shutil import copyfile

from PySide6.QtGui import QScreen

from models import Settings


def load_settings(path: Path, screens: list[QScreen]) -> Settings:
    if not path.exists():
        return Settings(model=os.environ.get("OPENAI_MODEL", ""),
                        api_key=os.environ.get("OPENAI_API_KEY", ""))
    values = json.loads(path.read_text("utf-8"))
    if not isinstance(values, dict):
        raise ValueError("设置文件应为 JSON 对象。")
    current = {field.name: type(field.default) for field in fields(Settings)
               if field.name != "api_key"}
    legacy = "version" not in values
    allowed = {
        "model": str, "pet_size": int, "topmost": bool, "quiet": bool,
        "x": int, "y": int, "monitor": str, "monitor_left": int, "monitor_top": int,
    } if legacy else current
    for name, value in values.items():
        if name not in allowed or type(value) is not allowed[name]:
            raise ValueError(f"设置字段 {name} 的格式不受支持。")
    settings = Settings(**{name: value for name, value in values.items() if name in current},
                        api_key=os.environ.get("OPENAI_API_KEY", ""))
    if settings.version != 2:
        raise ValueError("此版本无法读取该设置文件版本。")
    if not 120 <= settings.pet_size <= 320:
        raise ValueError("宠物尺寸应在 120 到 320 之间。")
    if not 1 <= settings.focus_minutes <= 180 or not 1 <= settings.break_minutes <= 60:
        raise ValueError("专注时长应为 1–180 分钟，休息时长应为 1–60 分钟。")
    settings.model = settings.model or os.environ.get("OPENAI_MODEL", "")
    if not legacy:
        return settings
    backup = path.with_name("settings.v1.bak.json")
    if not backup.exists():
        copyfile(path, backup)
    screen = next((screen for screen in screens if screen.name() == settings.monitor), None)
    if screen is not None and (values.get("x", -1), values.get("y", -1)) != (-1, -1):
        settings.pet_x = round((values.get("x", -1) - values.get("monitor_left", 0)) / screen.devicePixelRatio())
        settings.pet_y = round((values.get("y", -1) - values.get("monitor_top", 0)) / screen.devicePixelRatio())
    if screen is None:
        settings.monitor = ""
    save_settings(path, settings)
    return settings


def save_settings(path: Path, settings: Settings):
    values = asdict(settings)
    del values["api_key"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(path)
