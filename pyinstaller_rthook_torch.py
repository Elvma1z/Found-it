# Custom runtime hooks run before PyInstaller's automatic per-package ones,
# including pyi_rth_pyqt5.py, which prepends sys._MEIPASS to PATH before
# main.py starts. That reordering defeats the "import torch before PyQt5"
# rule main.py otherwise follows, and breaks torch's c10.dll init with
# WinError 1114. Importing torch here guarantees it finishes loading its
# own DLLs first, regardless of what any later hook does to PATH.
import torch  # noqa: F401
