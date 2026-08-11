import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller extracts bundled datas to a temp dir at _MEIPASS, mirroring
    # the source tree layout given to the spec file's `datas`.
    _RESOURCES_DIR = Path(sys._MEIPASS) / "found_it" / "resources"
else:
    _RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"

ICON_PATH = _RESOURCES_DIR / "app_icon.ico"
