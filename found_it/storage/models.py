from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from found_it.config import DETECTION_CONFIDENCE, DETECTION_FRAME_SKIP, DEWARP_ENABLED


@dataclass
class DetectedItem:
    label: str
    confidence: float
    camera_id: int
    zone_x: float
    zone_y: float
    bbox_x1: int
    bbox_y1: int
    bbox_x2: int
    bbox_y2: int
    snapshot_path: Optional[str] = None
    zone_name: Optional[str] = None
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    is_active: bool = True


@dataclass
class RoomZone:
    name: str
    x1: float
    y1: float
    x2: float
    y2: float


def default_cameras() -> list:
    return [
        {"id": 0, "label": "Camera 0", "enabled": True, "x": 0.3, "y": 0.3, "is_360": False},
        {"id": 1, "label": "Camera 1", "enabled": True, "x": 3.7, "y": 3.7, "is_360": False},
    ]


@dataclass
class RoomConfig:
    width_m: float = 4.0
    height_m: float = 4.0
    cameras: list = field(default_factory=default_cameras)
    zones: list = field(default_factory=list)


@dataclass
class AppSettings:
    detection_confidence: float = DETECTION_CONFIDENCE
    detection_frame_skip: int = DETECTION_FRAME_SKIP
    dewarp_default: bool = DEWARP_ENABLED
