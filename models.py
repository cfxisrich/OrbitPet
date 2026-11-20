from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    state: str
    detail: str
    updated_at: str
    turn_id: str = ""


@dataclass
class Settings:
    version: int = 2
    model: str = ""
    api_key: str = ""
    pet_size: int = 200
    topmost: bool = True
    quiet: bool = False
    pet_visible: bool = True
    monitor: str = ""
    pet_x: int = -1
    pet_y: int = -1
    main_geometry: str = ""
    main_maximized: bool = False
    focus_minutes: int = 25
    break_minutes: int = 5
    restore_shortcut: str = "Ctrl+Alt+P"


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    created_at: str


@dataclass(frozen=True)
class Activity:
    id: str
    text: str
    kind: str
    created_at: str


STATE_LABELS = {
    "idle": "空闲",
    "thinking": "思考中",
    "running": "执行中",
    "waiting": "需要你处理",
    "completed": "本轮完成",
    "failed": "失败",
    "interrupted": "已中断",
    "unknown": "状态未确认",
    "offline": "未连接",
}
