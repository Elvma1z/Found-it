from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from found_it.device.device_scanner import DeviceScanner
from found_it.gui import ds
from found_it.gui.file_search_panel import file_type_meta, human_size
from found_it.gui.help_info import HelpInfoMixin

ADB_URL = "https://developer.android.com/tools/releases/platform-tools"


class DeviceSearchPanel(QWidget, HelpInfoMixin):
    """Other devices: connect an Android phone over USB-C (ADB), index its
    files and search them the same way as files on this PC."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner = DeviceScanner()
        self._results = []
        self._indexed = 0
        self._init_help_info()
        self._setup_ui()
        self._setup_timer()
        self._update_adb_status()
        self._sync_connection_ui()

    def apply_theme(self, palette: dict):
        self._apply_help_theme(palette)
        self._sync_connection_ui()

    def status_summary(self) -> str:
        if self.scanner.is_connected():
            return f"Connected to {self.scanner.get_device_name()}"
        return "ADB ready" if self.scanner.is_adb_available() else "ADB not found"

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header = ds.PageHeader("Other devices", "Connect an Android phone over USB-C and search its files.")
        header.add(self._make_info_toggle())
        self.adb_status = ds.Badge("ADB found", "success", dot=True)
        header.add(self.adb_status)
        layout.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(12)

        # --- Device ---
        device = ds.GlassPanel("Device", "smartphone")
        device.setFixedWidth(340)
        body = device.body_layout

        card = ds.Card(14, 14)
        card_row = QHBoxLayout()
        card_row.setSpacing(14)
        self.device_icon = QLabel()
        self.device_icon.setFixedSize(44, 44)
        self.device_icon.setAlignment(Qt.AlignCenter)
        card_row.addWidget(self.device_icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.device_label = ds.text("No device", "h3")
        col.addWidget(self.device_label)
        self.device_sub = ds.text("Plug in via USB-C", "small")
        col.addWidget(self.device_sub)
        card_row.addLayout(col, 1)
        self.connected_badge = ds.Badge("Connected", "success", dot=True)
        card_row.addWidget(self.connected_badge)
        card.layout_.addLayout(card_row)
        body.addWidget(card)

        self.device_details = ds.DetailList()
        body.addWidget(self.device_details)

        self.progress_bar = ds.ProgressBar("Scanning device…")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        body.addWidget(self.progress_bar)

        self.steps = QWidget()
        steps = QVBoxLayout(self.steps)
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(8)
        self._step_numbers = []
        for i, step in enumerate((
            "Connect your device via USB-C",
            "Enable USB debugging (Settings › Developer options)",
            "Accept the debugging prompt on the phone",
        )):
            num = QLabel(str(i + 1))
            num.setFixedSize(20, 20)
            num.setAlignment(Qt.AlignCenter)
            self._step_numbers.append(num)
            steps.addLayout(ds.hbox(num, ds.text(step, "small", wrap=True), spacing=10, stretch_at=1))
        body.addWidget(self.steps)

        self.status_label = ds.text("", "caption", wrap=True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self.status_label)
        body.addStretch(1)

        self.connect_btn = ds.Button("Connect", "primary", "plug")
        self.connect_btn.clicked.connect(lambda: self._do_connect())
        body.addWidget(self.connect_btn)
        self.scan_btn = ds.Button("Scan device", "success", "scan-line")
        self.scan_btn.clicked.connect(self._start_scan)
        self.disconnect_btn = ds.Button("Disconnect", "danger", "unplug")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.connected_actions = QWidget()
        self.connected_actions.setLayout(ds.hbox(self.scan_btn, self.disconnect_btn, stretch_at=0))
        body.addWidget(self.connected_actions)
        self._add_help(
            None,
            "Connect a phone or tablet over USB-C with debugging enabled, then "
            "click Connect. Once connected, Scan device indexes its files so "
            "you can search them the same way as files on this PC.",
            layout=body,
        )
        row.addWidget(device)

        # --- Search device ---
        search = ds.GlassPanel("Search device", "search", padding=12)
        sb = search.body_layout
        self.search_input = ds.TextInput("Describe the file you're looking for...", icon="sparkles")
        self.search_input.returnPressed.connect(self._on_search)
        self.search_btn = ds.Button("Search", "primary")
        self.search_btn.clicked.connect(self._on_search)
        sb.addLayout(ds.hbox(self.search_input, self.search_btn, stretch_at=0))
        self.results_label = ds.text("", "eyebrow")
        self.results_label.hide()
        sb.addWidget(self.results_label)
        self.results_list = ds.RowList("Connect and scan a device first.", "smartphone")
        self.results_list.currentRowChanged.connect(self._on_result_select)
        sb.addWidget(self.results_list, 1)
        self.preview_label = self.status_label
        row.addWidget(search, 1)

        layout.addLayout(row, 1)
        ds.on_theme(self, lambda _p: self._sync_connection_ui())

    def _setup_timer(self):
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(500)

    # ---------------------------------------------------------------- state

    def _sync_connection_ui(self):
        p = ds.pal()
        connected = self.scanner.is_connected()
        scanning = self.scanner.is_scanning() if connected else False
        from found_it.gui.icons import get_pixmap
        self.device_icon.setPixmap(get_pixmap("smartphone" if connected else "usb",
                                              p["accent_text"] if connected else p["text3"], 22))
        self.device_icon.setStyleSheet(
            f"background: {p['accent_soft'] if connected else p['surface3']}; border-radius: 10px;")
        for num in self._step_numbers:
            num.setStyleSheet(
                f"background: {p['surface3']}; color: {p['text2']}; border-radius: 10px;"
                "font-size: 11px; font-weight: 600;")
        self.connected_badge.setVisible(connected)
        self.steps.setVisible(not connected)
        self.device_details.setVisible(connected)
        self.connect_btn.setVisible(not connected)
        self.connected_actions.setVisible(connected)
        self.search_btn.setEnabled(self._indexed > 0 or self.scanner.file_count() > 0)
        if connected:
            name = self.scanner.get_device_name()
            self.device_label.setText(name)
            self.device_sub.setText("USB debugging on")
            count = self.scanner.file_count()
            self.device_details.set_items([
                ("Serial", self.scanner.get_connected_serial() or "—", True),
                ("Indexed", f"{count:,} files" if count else "Not scanned yet"),
            ])
            if not self._results:
                self.results_list.set_empty(
                    f"Describe a file to search {name}." if count else "Scan the device to search its files.",
                    "smartphone")
        else:
            self.device_label.setText("No device")
            self.device_sub.setText("Plug in via USB-C")
            if not self._results:
                self.results_list.set_empty("Connect and scan a device first.", "smartphone")
        self.progress_bar.setVisible(scanning)

    def _update_adb_status(self):
        if self.scanner.is_adb_available():
            self.adb_status.set_text("ADB found", "success")
        else:
            self.adb_status.set_text("ADB not found", "danger")
            self.status_label.setText(f"Install Android platform-tools to connect a phone: {ADB_URL}")

    def _do_connect(self, serial: Optional[str] = None):
        self.status_label.setText("Looking for devices…")
        self.connect_btn.setEnabled(False)

        if not self.scanner.is_adb_available():
            self.status_label.setText(f"ADB not found. Install Android platform-tools: {ADB_URL}")
            self.connect_btn.setEnabled(True)
            return

        if self.scanner.connect(serial):
            self.status_label.setText("Connected. Scan the device to index its files.")
        else:
            self.status_label.setText("No matching device found. Follow the steps above, then try again.")
        self.connect_btn.setEnabled(True)
        self._sync_connection_ui()

    def connect_saved_device(self, serial: str):
        self._do_connect(serial)

    def get_connected_serial(self) -> Optional[str]:
        return self.scanner.get_connected_serial()

    def _start_scan(self):
        if not self.scanner.is_connected():
            return
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.scan_btn.setEnabled(False)
        self.status_label.setText("")
        self.scanner.start_scan(
            progress_callback=self._on_progress,
            done_callback=self._on_scan_done
        )

    def _on_progress(self, message):
        self.progress_bar.set_detail(message)

    def _on_scan_done(self, count):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self._indexed = count
        self.status_label.setText(f"Done. {count:,} files indexed from the device.")
        self._sync_connection_ui()

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        if self.scanner.is_scanning():
            self.status_label.setText("Still scanning, please wait…")
            return
        if self.scanner.file_count() == 0:
            self.results_list.set_empty("Connect and scan a device first.", "smartphone")
            return
        self._results = self.scanner.search(query, top_k=30)
        self.results_list.set_empty(f'No files on the device match "{query}".', "search-x")
        self._show_results()

    def _show_results(self):
        self.results_list.clear()
        self.results_label.setText(f"{len(self._results)} results")
        self.results_label.setVisible(bool(self._results))
        for i, result in enumerate(self._results):
            icon, label, color = file_type_meta(result.file_type)
            item = ds.make_row("result", icon=icon, color=color, title=result.name,
                               subtitle=f"{label} · {human_size(result.size_bytes)}",
                               path=result.path, score=result.score)
            item.setData(Qt.UserRole, i)
            self.results_list.addItem(item)

    def _on_result_select(self, row):
        pass

    def _disconnect(self):
        self.scanner.disconnect()
        self._results = []
        self._indexed = 0
        self.results_list.clear()
        self.results_label.hide()
        self.status_label.setText("Device disconnected.")
        self._update_adb_status()
        self._sync_connection_ui()

    def _poll_status(self):
        if self.scanner.is_scanning():
            self.progress_bar.set_detail(f"{self.scanner.file_count():,} files embedded")
