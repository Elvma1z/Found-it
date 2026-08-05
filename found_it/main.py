import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# torch must be imported before PyQt5 on Windows: PyQt5 resets the DLL
# search path (SetDllDirectoryW), which otherwise breaks torch's DLL loading.
import torch  # noqa: F401

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont

from found_it.gui.splash import create_splash_screen, splash_show_message
from found_it.gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    app.setStyleSheet("""
        QToolTip {
            background-color: #2a2a3e;
            color: #e0e0e0;
            border: 1px solid #444;
        }
    """)

    splash = create_splash_screen()
    splash.show()
    splash_show_message(splash, "Starting up...")
    app.processEvents()

    window = MainWindow()

    splash.finish(window)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
