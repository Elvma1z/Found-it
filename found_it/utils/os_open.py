import os
import platform
import subprocess


def open_file(path: str):
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


def open_containing_folder(path: str):
    folder = os.path.dirname(path)
    if platform.system() == "Windows":
        subprocess.run(["explorer", folder])
    elif platform.system() == "Darwin":
        subprocess.run(["open", folder])
    else:
        subprocess.run(["xdg-open", folder])
