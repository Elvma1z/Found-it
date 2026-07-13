import json
from pathlib import Path

from found_it.config import DATA_DIR, ROOM_WIDTH_M, ROOM_HEIGHT_M
from found_it.storage.models import RoomConfig


CONFIG_FILE = DATA_DIR / "room_config.json"


def load_room_config() -> RoomConfig:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        return RoomConfig(
            width_m=data.get("width_m", ROOM_WIDTH_M),
            height_m=data.get("height_m", ROOM_HEIGHT_M),
            camera0_corner=data.get("camera0_corner", "top-left"),
            camera1_corner=data.get("camera1_corner", "bottom-right"),
            center_camera_enabled=data.get("center_camera_enabled", False),
            center_camera_position=data.get("center_camera_position", "center"),
            zones=data.get("zones", []),
        )
    return RoomConfig()


def save_room_config(config: RoomConfig):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "width_m": config.width_m,
        "height_m": config.height_m,
        "camera0_corner": config.camera0_corner,
        "camera1_corner": config.camera1_corner,
        "center_camera_enabled": config.center_camera_enabled,
        "center_camera_position": config.center_camera_position,
        "zones": config.zones,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
