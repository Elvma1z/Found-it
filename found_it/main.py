import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# torch must be imported before PyQt5 on Windows: PyQt5 resets the DLL
# search path (SetDllDirectoryW), which otherwise breaks torch's DLL loading.
import torch  # noqa: F401

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QIcon

from found_it.gui.splash import create_splash_screen, splash_show_message
from found_it.gui.main_window import MainWindow
from found_it.utils.app_settings import load_app_settings
from found_it.utils.themes import get_palette
from found_it.gui.ds import apply_app_theme
from found_it.utils.resources import ICON_PATH


def main():
    app = QApplication(sys.argv)

    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    settings = load_app_settings()
    font = QFont(settings.font_family, 10)
    app.setFont(font)

    # The whole design system is one application stylesheet; installing it
    # before anything is created means the splash and first paint match.
    palette = get_palette(settings.theme)
    apply_app_theme(palette, settings.font_family)

    splash = create_splash_screen(palette)
    splash.show()
    splash_show_message(splash, "Starting up...")
    app.processEvents()

    window = MainWindow()

    splash.finish(window)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
