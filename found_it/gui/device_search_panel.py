import os
import platform
import subprocess
from typing import Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QProgressBar, QSplitter
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from found_it.device.device_scanner import DeviceScanner, DeviceSearchResult
from found_it.gui.icons import get_icon, ICON_SIZE
from found_it.utils.themes import get_palette, widget_qss, repolish


class DeviceSearchPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner = DeviceScanner()
        self.palette = get_palette("Indigo")
        self._setup_ui()
        self._setup_timer()
        self.apply_theme(self.palette)

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.setStyleSheet(widget_qss(palette))
        self.connect_btn.setIcon(get_icon("link", palette["text_dim"]))
        self.disconnect_btn.setIcon(get_icon("unlink", "#e57373"))
        self.search_btn.setIcon(get_icon("search", "#ffffff"))
        self._show_results()
        repolish(self)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Other Devices")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        layout.addWidget(title)

        desc = QLabel("Connect a device via USB-C and search its files")
        desc.setProperty("cls", "muted")
        layout.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        conn_row = QHBoxLayout()

        self.adb_status = QLabel()
        self.adb_status.setStyleSheet("font-size: 12px;")
        conn_row.addWidget(self.adb_status)

        conn_row.addStretch()

        self.connect_btn = QPushButton(" Connect")
        self.connect_btn.setIconSize(ICON_SIZE)
        self.connect_btn.setProperty("cls", "secondary")
        self.connect_btn.clicked.connect(lambda: self._do_connect())
        conn_row.addWidget(self.connect_btn)

        self.scan_btn = QPushButton("Scan Device")
        self.scan_btn.setEnabled(False)
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50; color: white;
                border: none; border-radius: 4px;
                padding: 6px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #43a047; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self.scan_btn.clicked.connect(self._start_scan)
        conn_row.addWidget(self.scan_btn)

        self.disconnect_btn = QPushButton(" Disconnect")
        self.disconnect_btn.setIconSize(ICON_SIZE)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setProperty("cls", "destructive")
        self.disconnect_btn.clicked.connect(self._disconnect)
        conn_row.addWidget(self.disconnect_btn)

        layout.addLayout(conn_row)

        self.device_label = QLabel("")
        self.device_label.setProperty("cls", "status")
        layout.addWidget(self.device_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setProperty("cls", "hint")
        layout.addWidget(self.status_label)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setProperty("cls", "sep")
        layout.addWidget(sep2)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Describe the file you're looking for...")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        self.search_btn = QPushButton(" Search")
        self.search_btn.setIconSize(ICON_SIZE)
        self.search_btn.setProperty("cls", "primary")
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.results_label = QLabel("Results")
        self.results_label.setProperty("cls", "muted")
        layout.addWidget(self.results_label)

        content_splitter = QSplitter(Qt.Horizontal)

        self.results_list = QListWidget()
        self.results_list.currentRowChanged.connect(self._on_result_select)
        content_splitter.addWidget(self.results_list)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)

        self.preview_label = QLabel("Select a result for details")
        self.preview_label.setWordWrap(True)
        self.preview_label.setProperty("cls", "muted")
        right_layout.addWidget(self.preview_label)

        right_layout.addStretch()
        content_splitter.addWidget(right_panel)
        content_splitter.setSizes([400, 300])

        layout.addWidget(content_splitter)

        self._results = []
        self._update_adb_status()

    def _setup_timer(self):
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(500)

    def _update_adb_status(self):
        if self.scanner.is_adb_available():
            self.adb_status.setText("ADB: Found")
            self.adb_status.setStyleSheet("color: #4caf50; font-size: 12px;")
        else:
            self.adb_status.setText("ADB: Not found — install Android platform-tools")
            self.adb_status.setStyleSheet("color: #e53935; font-size: 12px;")

    def _do_connect(self, serial: Optional[str] = None):
        self.status_label.setText("Looking for devices...")
        self.connect_btn.setEnabled(False)

        if not self.scanner.is_adb_available():
            self.status_label.setText(
                "ADB not found. Install Android platform-tools:\n"
                "https://developer.android.com/tools/releases/platform-tools"
            )
            self.connect_btn.setEnabled(True)
            return

        if self.scanner.connect(serial):
            name = self.scanner.get_device_name()
            self.device_label.setText(f"Connected: {name}")
            self.scan_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(True)
            self.connect_btn.setEnabled(False)
            self.status_label.setText("Device connected. Click Scan to index files.")
        else:
            self.status_label.setText(
                "No matching device found.\n"
                "1. Connect your device via USB-C\n"
                "2. Enable USB debugging (Settings > Developer Options)\n"
                "3. Accept the debugging prompt on your device"
            )
            self.connect_btn.setEnabled(True)

    def connect_saved_device(self, serial: str):
        self._do_connect(serial)

    def get_connected_serial(self) -> Optional[str]:
        return self.scanner.get_connected_serial()

    def _start_scan(self):
        if not self.scanner.is_connected():
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.scan_btn.setEnabled(False)
        self.status_label.setText("Scanning device...")

        self.scanner.start_scan(
            progress_callback=self._on_progress,
            done_callback=self._on_scan_done
        )

    def _on_progress(self, message):
        self.status_label.setText(message)

    def _on_scan_done(self, count):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.status_label.setText(
            f"Done! {count} files indexed from device"
        )

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        if self.scanner.is_scanning():
            self.status_label.setText("Still scanning, please wait...")
            return

        if self.scanner.file_count() == 0:
            self.status_label.setText("No files indexed. Connect and scan first.")
            return

        self.status_label.setText(f"Searching: {query}")
        self._results = self.scanner.search(query, top_k=30)
        self._show_results()

    def _show_results(self):
        self.results_list.clear()
        self.results_label.setText(f"Results ({len(self._results)})")

        for i, result in enumerate(self._results):
            icon_name = {"image": "image", "code": "code", "text": "file-text"}.get(
                result.file_type, "file"
            )
            size_kb = result.size_bytes / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            score_str = f"{result.score:.0%}"

            text = (
                f"{result.name}\n"
                f"  {result.path}\n"
                f"  {size_str} | Match: {score_str}"
            )

            item = QListWidgetItem(get_icon(icon_name, self.palette["text_dim"]), text)
            item.setData(Qt.UserRole, i)
            self.results_list.addItem(item)

    def _on_result_select(self, row):
        if row < 0 or row >= len(self._results):
            return

        result = self._results[row]
        preview = (
            f"Name: {result.name}\n"
            f"Path: {result.path}\n"
            f"Type: {result.file_type}\n"
            f"Size: {result.size_bytes / 1024:.0f} KB\n"
            f"Match: {result.score:.1%}"
        )
        self.preview_label.setText(preview)

    def _disconnect(self):
        self.scanner.disconnect()
        self.device_label.setText("")
        self.scan_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.setEnabled(True)
        self.status_label.setText("Device disconnected.")
        self.results_list.clear()
        self._results = []
        self._update_adb_status()

    def _poll_status(self):
        if self.scanner.is_scanning():
            count = self.scanner.file_count()
            self.status_label.setText(f"Indexing... {count} files embedded")
