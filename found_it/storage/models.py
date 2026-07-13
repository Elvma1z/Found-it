from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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


@dataclass
class RoomConfig:
    width_m: float = 4.0
    height_m: float = 4.0
    camera0_corner: str = "top-left"
    camera1_corner: str = "bottom-right"
    center_camera_enabled: bool = False
    center_camera_position: str = "center"
    zones: list = field(default_factory=list)
