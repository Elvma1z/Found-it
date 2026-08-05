import json

from found_it.config import DATA_DIR
from found_it.storage.models import AppSettings


SETTINGS_FILE = DATA_DIR / "app_settings.json"


def load_app_settings() -> AppSettings:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        defaults = AppSettings()
        return AppSettings(
            detection_confidence=data.get("detection_confidence", defaults.detection_confidence),
            detection_frame_skip=data.get("detection_frame_skip", defaults.detection_frame_skip),
            dewarp_default=data.get("dewarp_default", defaults.dewarp_default),
            active_room_id=data.get("active_room_id", defaults.active_room_id),
            room_tracker_layout=data.get("room_tracker_layout", defaults.room_tracker_layout),
        )
    return AppSettings()


def save_app_settings(settings: AppSettings):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "detection_confidence": settings.detection_confidence,
        "detection_frame_skip": settings.detection_frame_skip,
        "dewarp_default": settings.dewarp_default,
        "active_room_id": settings.active_room_id,
        "room_tracker_layout": settings.room_tracker_layout,
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
