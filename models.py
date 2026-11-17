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
    model: str = ""
    api_key: str = ""
    pet_size: int = 200
    topmost: bool = True
    quiet: bool = False
    x: int = -1
    y: int = -1
    monitor: str = ""
    monitor_left: int = 0
    monitor_top: int = 0


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
