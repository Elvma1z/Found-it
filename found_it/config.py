import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_DIR = DATA_DIR / "db"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
CALIBRATION_DIR = DATA_DIR / "calibration"

DB_PATH = DB_DIR / "found_it.db"

CAMERA_IDS = [0, 1]
CENTER_CAMERA_ENABLED = False
CENTER_CAMERA_ID = 2
ALL_CAMERA_IDS = [0, 1, 2]

CAMERA_RESOLUTION = (640, 480)
CAMERA_FPS = 15

YOLO_MODEL = "yolov8n.pt"
DETECTION_CONFIDENCE = 0.4
DETECTION_FRAME_SKIP = 3

ITEM_INACTIVE_SECONDS = 300

DEWARP_ENABLED = False
FISHEYE_FOV = 180.0

CAMERA_CORNERS = ["top-left", "bottom-right"]

ROOM_WIDTH_M = 4.0
ROOM_HEIGHT_M = 4.0

CAMERA_LABELS = {0: "Cam 0", 1: "Cam 1", 2: "360"}
