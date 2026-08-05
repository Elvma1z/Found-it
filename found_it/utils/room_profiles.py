import json
from typing import List

from found_it.config import DATA_DIR, ROOM_WIDTH_M, ROOM_HEIGHT_M
from found_it.storage.models import RoomConfig, default_cameras


PROFILES_FILE = DATA_DIR / "room_profiles.json"
LEGACY_CONFIG_FILE = DATA_DIR / "room_config.json"


def profile_from_dict(data: dict) -> RoomConfig:
    return RoomConfig(
        id=data.get("id", "main"),
        name=data.get("name", "Main Room"),
        width_m=data.get("width_m", ROOM_WIDTH_M),
        height_m=data.get("height_m", ROOM_HEIGHT_M),
        cameras=data.get("cameras", default_cameras()),
        zones=data.get("zones", []),
    )


def profile_to_dict(profile: RoomConfig) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "width_m": profile.width_m,
        "height_m": profile.height_m,
        "cameras": profile.cameras,
        "zones": profile.zones,
    }


def profiles_to_list(profiles: List[RoomConfig]) -> list:
    return [profile_to_dict(p) for p in profiles]


def load_room_profiles() -> List[RoomConfig]:
    if PROFILES_FILE.exists():
        with open(PROFILES_FILE, "r") as f:
            data = json.load(f)
        profiles = [profile_from_dict(p) for p in data]
        if profiles:
            return profiles

    if LEGACY_CONFIG_FILE.exists():
        with open(LEGACY_CONFIG_FILE, "r") as f:
            legacy = json.load(f)
        migrated = RoomConfig(
            id="main",
            name="Main Room",
            width_m=legacy.get("width_m", ROOM_WIDTH_M),
            height_m=legacy.get("height_m", ROOM_HEIGHT_M),
            cameras=legacy.get("cameras", default_cameras()),
            zones=legacy.get("zones", []),
        )
        save_room_profiles([migrated])
        return [migrated]

    default_profile = RoomConfig()
    save_room_profiles([default_profile])
    return [default_profile]


def save_room_profiles(profiles: List[RoomConfig]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles_to_list(profiles), f, indent=2)
