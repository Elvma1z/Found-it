import json

from found_it.config import DATA_DIR
from found_it.storage.models import AppSettings
from found_it.version import PRE_VERSIONING_VERSION


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
            room_setup_layout=data.get("room_setup_layout", defaults.room_setup_layout),
            font_family=data.get("font_family", defaults.font_family),
            theme=data.get("theme", defaults.theme),
            title_hotkey_action=data.get("title_hotkey_action", defaults.title_hotkey_action),
            title_hotkey_label=data.get("title_hotkey_label", defaults.title_hotkey_label),
            nav_tab_order=data.get("nav_tab_order", defaults.nav_tab_order),
            dock_panel_order=data.get("dock_panel_order", defaults.dock_panel_order),
            # A settings file written before these keys existed belongs to
            # someone already using the app, not to a fresh install - so
            # they get release notes for what changed, not the tutorial.
            last_seen_version=data.get("last_seen_version", PRE_VERSIONING_VERSION),
            tutorial_completed=data.get("tutorial_completed", True),
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
        "room_setup_layout": settings.room_setup_layout,
        "font_family": settings.font_family,
        "theme": settings.theme,
        "title_hotkey_action": settings.title_hotkey_action,
        "title_hotkey_label": settings.title_hotkey_label,
        "nav_tab_order": settings.nav_tab_order,
        "dock_panel_order": settings.dock_panel_order,
        "last_seen_version": settings.last_seen_version,
        "tutorial_completed": settings.tutorial_completed,
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
