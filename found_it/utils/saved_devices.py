import json
from typing import List

from found_it.config import DATA_DIR


SAVED_DEVICES_FILE = DATA_DIR / "saved_devices.json"


def load_saved_devices() -> List[dict]:
    if SAVED_DEVICES_FILE.exists():
        with open(SAVED_DEVICES_FILE, "r") as f:
            return json.load(f)
    return []


def save_saved_devices(devices: List[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SAVED_DEVICES_FILE, "w") as f:
        json.dump(devices, f, indent=2)
