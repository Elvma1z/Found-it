import json

from found_it.config import DATA_DIR, ROOM_WIDTH_M, ROOM_HEIGHT_M
from found_it.storage.models import RoomConfig, default_cameras


CONFIG_FILE = DATA_DIR / "room_config.json"


def load_room_config() -> RoomConfig:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        return RoomConfig(
            width_m=data.get("width_m", ROOM_WIDTH_M),
            height_m=data.get("height_m", ROOM_HEIGHT_M),
            cameras=data.get("cameras", default_cameras()),
            zones=data.get("zones", []),
        )
    return RoomConfig()


def save_room_config(config: RoomConfig):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "width_m": config.width_m,
        "height_m": config.height_m,
        "cameras": config.cameras,
        "zones": config.zones,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
