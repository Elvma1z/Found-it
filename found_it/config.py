import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller extracts bundled modules to a temp dir that's wiped on
    # exit, so __file__ can't locate persistent storage. Anchor to the exe
    # itself, which lives in the actual install directory.
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_DIR = DATA_DIR / "db"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
CALIBRATION_DIR = DATA_DIR / "calibration"
FACES_DIR = DATA_DIR / "faces"

DB_PATH = DB_DIR / "found_it.db"
INDEX_DB_PATH = DB_DIR / "file_index.db"

CAMERA_RESOLUTION = (640, 480)
CAMERA_FPS = 15

YOLO_MODEL = str(BASE_DIR / "yolov8n.pt")
DETECTION_CONFIDENCE = 0.4
DETECTION_FRAME_SKIP = 3
DETECTION_IMGSZ = 480

ITEM_INACTIVE_SECONDS = 300

DEWARP_ENABLED = False
FISHEYE_FOV = 180.0

ROOM_WIDTH_M = 4.0
ROOM_HEIGHT_M = 4.0

CAMERA_LABELS = {0: "Cam 0", 1: "Cam 1", 2: "360"}
