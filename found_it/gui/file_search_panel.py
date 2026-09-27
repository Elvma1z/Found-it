import os
import string
import platform
import threading
from typing import List

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QInputDialog, QTabWidget,
    QStackedWidget, QCheckBox,
)

from found_it.fileindex.search import FileSearchEngine, SearchResult
from found_it.gui import ds
from found_it.gui.help_info import HelpInfoMixin
from found_it.gui.people_panel import PeopleGalleryWidget
from found_it.utils.os_open import open_file, open_containing_folder
from found_it.utils.themes import FILE_TYPE_COLORS

FILE_TYPES = {
    "image": ("image", "Image"),
    "text": ("file-text", "Document"),
    "code": ("code", "Code"),
}


def file_type_meta(file_type: str):
    icon, label = FILE_TYPES.get(file_type, ("file", "File"))
    return icon, label, FILE_TYPE_COLORS.get(file_type, "#94a3b8")


def human_size(size_bytes: int) -> str:
    kb = size_bytes / 1024
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb:.0f} KB"


class SearchTab(QWidget, HelpInfoMixin):
    """Prompt or upload-an-image search across every indexed file - photos
    of people, scenery, objects, or plain documents - by CLIP visual/text
    similarity. Named people from the People tab are used automatically to
    narrow a query that mentions one of them by name."""

    _image_search_done = pyqtSignal(list, str)

    def __init__(self, engine: FileSearchEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._init_help_info()
        self._setup_ui()
        self._setup_timer()
        self._image_search_done.connect(self._on_image_search_done)

    def apply_theme(self, palette: dict):
        self._apply_help_theme(palette)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # --- Search panel ---
        top = ds.GlassPanel(padding=16)
        body = top.body_layout

        self.search_input = ds.TextInput(
            "Describe it — 'vacation photo with mountains', or a person's name", icon="sparkles", size="lg")
        self.search_input.returnPressed.connect(self._on_search)
        self.search_btn = ds.Button("Search", "primary", size="lg")
        self.search_btn.clicked.connect(self._on_search)
        self.image_search_btn = ds.Button("By image", "secondary", "image-up", size="lg")
        self.image_search_btn.setToolTip("Pick a picture and find visually similar indexed images")
        self.image_search_btn.clicked.connect(self._search_by_image)
        body.addLayout(ds.hbox(self.search_input, self.search_btn, self.image_search_btn, stretch_at=0))
        self._add_help(
            None,
            "Type a description (\"vacation photo with mountains\"), or a name "
            "from the People tab, and press Search - or use \"By image\" "
            "to find files that look like a picture you already have.",
            layout=body,
        )

        self.full_pc_checkbox = QCheckBox("Scan entire PC")
        self.full_pc_checkbox.setChecked(True)
        self.full_pc_checkbox.stateChanged.connect(self._update_folder_label)
        self.folder_label = ds.text("", "caption")
        self.add_folder_btn = ds.Button("Add folder", "ghost", "folder-plus", size="sm")
        self.add_folder_btn.clicked.connect(self._add_folder)
        self.add_image_btn = ds.Button("Add named image", "ghost", "image-plus", size="sm")
        self.add_image_btn.clicked.connect(self._add_named_image)
        self.scan_btn = ds.Button("Scan", "success", "scan-line", size="sm")
        self.scan_btn.clicked.connect(self._start_scan)
        self.cancel_scan_btn = ds.Button("Cancel", "secondary", "x", size="sm")
        self.cancel_scan_btn.setEnabled(False)
        self.cancel_scan_btn.hide()
        self.cancel_scan_btn.clicked.connect(self._cancel_scan)
        body.addLayout(ds.hbox(
            self.full_pc_checkbox, self.folder_label, self.add_folder_btn, self.add_image_btn,
            self.scan_btn, self.cancel_scan_btn, spacing=12, stretch_at=1))
        self._add_help(
            None,
            "\"Scan entire PC\" searches every drive (skipping system folders like Windows, "
            "Program Files and AppData). Untick it to scan only folders you add. \"Add named "
            "image\" gives one picture a name (e.g. \"Passport\") so typing that name finds it "
            "instantly. Photos found here also fill the People tab.",
            layout=body,
        )

        self.progress_bar = ds.ProgressBar("Indexing…")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        body.addWidget(self.progress_bar)
        self.status_label = ds.text("", "caption", wrap=True)
        body.addWidget(self.status_label)
        layout.addWidget(top)

        # --- Results + Preview ---
        row = QHBoxLayout()
        row.setSpacing(12)

        self.results_panel = ds.GlassPanel("Results", "list-filter", padding=8)
        self.results_label = ds.Badge("0")
        self.results_label.hide()
        self.results_panel.add_action(self.results_label)
        self.results_list = ds.RowList("Describe what you're looking for above.", "search")
        self.results_list.currentRowChanged.connect(self._on_result_select)
        self.results_panel.body_layout.addWidget(self.results_list)
        row.addWidget(self.results_panel, 3)

        self.preview_panel = ds.GlassPanel("Preview", "eye")
        pb = self.preview_panel.body_layout
        self.preview_stack = QStackedWidget()
        empty = ds.text("Select a result to preview it.", "caption")
        empty.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preview_stack.addWidget(empty)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(12)
        self.preview_box = QLabel()
        self.preview_box.setObjectName("previewBox")
        self.preview_box.setFixedHeight(150)
        self.preview_box.setAlignment(Qt.AlignCenter)
        self.preview_box.setWordWrap(True)
        dl.addWidget(self.preview_box)
        self.preview_title = ds.text("", "h3", wrap=True)
        dl.addWidget(self.preview_title)
        self.preview_details = ds.DetailList()
        dl.addWidget(self.preview_details)
        dl.addStretch(1)
        self.preview_stack.addWidget(detail)
        pb.addWidget(self.preview_stack, 1)

        self.open_btn = ds.Button("Open file", "primary", "external-link")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_file)
        self.open_dir_btn = ds.Button("Open folder", "secondary", "folder-open")
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.clicked.connect(self._open_folder)
        pb.addLayout(ds.hbox(self.open_btn, self.open_dir_btn))
        self.open_btn.setSizePolicy(self.open_btn.sizePolicy().Expanding, self.open_btn.sizePolicy().Fixed)
        self.open_dir_btn.setSizePolicy(self.open_dir_btn.sizePolicy().Expanding, self.open_dir_btn.sizePolicy().Fixed)
        row.addWidget(self.preview_panel, 2)
        layout.addLayout(row, 1)

        # Kept for older call sites.
        self.preview_label = self.preview_title

        self._folders: List[str] = []
        self._results: List[SearchResult] = []
        self._scan_was_cancelled = False
        self._update_folder_label()
        self._show_idle_status()
        ds.on_theme(self, self._style_preview_box)

    def _style_preview_box(self, p):
        self.preview_box.setStyleSheet(
            f"QLabel#previewBox {{ background: {p['surface2']}; border: 1px solid {p['border']};"
            "border-radius: 10px; }}")

    def _setup_timer(self):
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(500)

    def _stats(self):
        try:
            return self.engine.get_stats()
        except Exception:
            return None

    def status_summary(self) -> str:
        stats = self._stats()
        if not stats or not stats.get("embedded"):
            return "No files indexed yet"
        return f"{stats['embedded']:,} files indexed"

    def _show_idle_status(self):
        stats = self._stats()
        if stats and stats.get("embedded"):
            self.status_label.setText(
                f"{stats['embedded']:,} files indexed · {stats['images']:,} images · "
                f"{stats['texts']:,} texts · {stats['codes']:,} code")
        else:
            self.status_label.setText("No files indexed yet. Press Scan to build the index.")

    def _get_all_drives(self) -> List[str]:
        """Every locally reachable drive/volume root, so "Scan entire PC" isn't
        limited to just the folders the user thought to add by hand."""
        if platform.system() == "Windows":
            return [f"{letter}:\\" for letter in string.ascii_uppercase
                    if os.path.exists(f"{letter}:\\")]
        return ["/"]

    def _update_folder_label(self):
        extra = f" + {len(self._folders)} extra folder{'s' if len(self._folders) != 1 else ''}" if self._folders else ""
        if self.full_pc_checkbox.isChecked():
            self.folder_label.setText(f"Every drive, skipping Windows, Program Files and AppData{extra}")
        elif self._folders:
            names = [os.path.basename(f) or f for f in self._folders]
            self.folder_label.setText(f"Only: {', '.join(names)}")
        else:
            self.folder_label.setText("Only folders you add")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder to index")
        if folder and folder not in self._folders:
            self._folders.append(folder)
            self._update_folder_label()

    def _set_scanning(self, scanning: bool):
        self.progress_bar.setVisible(scanning)
        self.scan_btn.setVisible(not scanning)
        self.scan_btn.setEnabled(not scanning)
        self.cancel_scan_btn.setVisible(scanning)
        self.cancel_scan_btn.setEnabled(scanning)
        self.status_label.setVisible(not scanning)

    def _start_scan(self):
        if self.full_pc_checkbox.isChecked():
            drives = self._get_all_drives()
            roots = drives + [f for f in self._folders if f not in drives]
        else:
            roots = list(self._folders)

        if not roots:
            self.status_label.setText('Add a folder first, or tick "Scan entire PC".')
            return

        self._scan_was_cancelled = False
        self.progress_bar.setRange(0, 0)
        self.progress_bar.set_label("Indexing…", "")
        self._set_scanning(True)

        self.engine.start_indexing(
            roots,
            progress_callback=self._on_progress,
            done_callback=self._on_scan_done
        )

    def _cancel_scan(self):
        self._scan_was_cancelled = True
        self.cancel_scan_btn.setEnabled(False)
        self.progress_bar.set_label("Cancelling…", "")
        self.engine.cancel()

    def _add_named_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select an image to add",
            "", "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif)"
        )
        if not path:
            return

        default_name = os.path.splitext(os.path.basename(path))[0]
        name, ok = QInputDialog.getText(
            self, "Name this image", 'Name (e.g. "My Wallet"):', text=default_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        self.add_image_btn.setEnabled(False)
        self.status_label.setText(f'Adding "{name}"…')
        self.engine.add_named_image(path, name, done_callback=self._on_add_image_done)

    def _on_add_image_done(self, success: bool, name: str):
        self.add_image_btn.setEnabled(True)
        if success:
            self.status_label.setText(f'Added "{name}". Search for that name to find it instantly.')
        else:
            self.status_label.setText(
                f'Couldn\'t add "{name}" - image search needs open-clip-torch installed.'
            )

    def _on_progress(self, message):
        self.progress_bar.set_detail(message)

    def _on_scan_done(self, count):
        self._set_scanning(False)
        stats = self.engine.get_stats()
        prefix = "Cancelled." if self._scan_was_cancelled else "Done."
        self.status_label.setText(
            f"{prefix} {stats['total']:,} files found, {stats['embedded']:,} indexed "
            f"· {stats['images']:,} images · {stats['texts']:,} texts · {stats['codes']:,} code"
        )

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        if self.engine.is_indexing():
            self.status_label.setText("Still indexing, please wait…")
            return

        if len(self.engine.store) == 0:
            self.results_list.set_empty("No files indexed yet. Scan first.", "scan-line")
            self.status_label.setText("No files indexed yet. Scan first.")
            return

        self._results = self.engine.search(query, top_k=30)
        self.results_list.set_empty(f'No files match "{query}".', "search-x")
        self._show_results()

    def _search_by_image(self):
        if self.engine.is_indexing():
            self.status_label.setText("Still indexing, please wait…")
            return

        if len(self.engine.store) == 0:
            self.status_label.setText("No files indexed yet. Scan first.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Select an image to search with",
            "", "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif)"
        )
        if not path:
            return

        self.image_search_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.status_label.setText(f"Searching for images like {os.path.basename(path)}…")

        def worker():
            results = self.engine.search_by_image(path, top_k=30)
            self._image_search_done.emit(results, path)

        threading.Thread(target=worker, daemon=True).start()

    def _on_image_search_done(self, results, path):
        self.image_search_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self._results = results

        if not results:
            self.status_label.setText(
                f"No visual matches for {os.path.basename(path)} "
                "(image search needs open-clip-torch installed)."
            )
        else:
            self.status_label.setText(
                f"{len(results)} visual match{'es' if len(results) != 1 else ''} for {os.path.basename(path)}"
            )
        self._show_results()

    def _show_results(self):
        self.results_list.clear()
        self.results_label.set_text(str(len(self._results)))
        self.results_label.setVisible(bool(self._results))

        for i, result in enumerate(self._results):
            icon, label, color = file_type_meta(result.file_type)
            item = ds.make_row(
                "result", icon=icon, color=color, title=result.name,
                subtitle=f"{label} · {human_size(result.size_bytes)}", path=result.path,
                score=result.score,
            )
            item.setData(Qt.UserRole, i)
            self.results_list.addItem(item)
        if self._results:
            self.results_list.setCurrentRow(0)
        else:
            self._clear_preview()

    def _clear_preview(self):
        self.preview_stack.setCurrentIndex(0)
        self.open_btn.setEnabled(False)
        self.open_dir_btn.setEnabled(False)

    def _on_result_select(self, row):
        if row < 0 or row >= len(self._results):
            self._clear_preview()
            return

        result = self._results[row]
        icon, label, color = file_type_meta(result.file_type)
        p = ds.pal()
        self.preview_box.clear()
        shown = False
        if result.file_type == "image" and os.path.exists(result.path):
            pm = QPixmap(result.path)
            if not pm.isNull():
                dpr = self.devicePixelRatioF()
                scaled = pm.scaled(int((self.preview_box.width() - 2) * dpr), int(148 * dpr),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
                scaled.setDevicePixelRatio(dpr)
                self.preview_box.setPixmap(scaled)
                self.preview_box.setAlignment(Qt.AlignCenter)
                shown = True
        if not shown and result.text_preview:
            self.preview_box.setText(result.text_preview[:400])
            self.preview_box.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.preview_box.setStyleSheet(
                f"QLabel#previewBox {{ background: {p['surface2']}; border: 1px solid {p['border']};"
                f"border-radius: 10px; padding: 14px; color: {p['text2']};"
                'font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; }')
            shown = True
        else:
            self._style_preview_box(p)
        if not shown:
            from found_it.gui.icons import get_pixmap
            self.preview_box.setPixmap(get_pixmap(icon, color, 40))
            self.preview_box.setAlignment(Qt.AlignCenter)

        self.preview_title.setText(result.name)
        self.preview_details.set_items([
            ("Type", label),
            ("Size", human_size(result.size_bytes)),
            ("Match", f"{result.score * 100:.1f}%"),
            ("Path", result.path, True),
        ])
        self.preview_stack.setCurrentIndex(1)
        self.open_btn.setEnabled(True)
        self.open_dir_btn.setEnabled(True)

    def _open_file(self):
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        open_file(self._results[row].path)

    def _open_folder(self):
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        open_containing_folder(self._results[row].path)

    def _poll_status(self):
        if self.engine.is_indexing():
            stats = self.engine.get_stats()
            total = stats["total"]
            done = stats["indexed"]
            if total:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(done)
            self.progress_bar.set_detail(f"{done:,} / {total:,} files")


class FileSearchPanel(QWidget):
    """File search: a Search tab (prompt or upload-an-image, across photos,
    scenery, items, and files generally) and a People tab (browse/name the
    faces detected while indexing), sharing one search engine and index."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = FileSearchEngine()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.header = ds.PageHeader("File search", "Find photos, people, documents and code on this PC by describing them.")
        self.switcher = ds.SegmentedTabs([("search", "Search", "search"), ("people", "People", "users")])
        self.switcher.changed.connect(self._on_switch)
        self.header.add(self.switcher)
        layout.addWidget(self.header)

        # The QTabWidget still holds both pages (Settings > Customization
        # lifts them out and back); its own tab bar is replaced by the
        # segmented control above.
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.setDocumentMode(True)
        self.search_tab = SearchTab(self.engine)
        self.people_tab = PeopleGalleryWidget(self.engine)
        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.people_tab, "People")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        self.header.right.insertWidget(0, self.search_tab._make_info_toggle())
        self.people_tab.people_count_changed.connect(
            lambda n: self.switcher.set_label("people", f"People  {n}" if n else "People"))

    def status_summary(self) -> str:
        return self.search_tab.status_summary()

    def _on_switch(self, key: str):
        page = self.search_tab if key == "search" else self.people_tab
        index = self.tabs.indexOf(page)
        if index >= 0:
            self.tabs.setCurrentIndex(index)

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.people_tab:
            self.switcher.set_current("people")
            self.people_tab.refresh()
        elif widget is self.search_tab:
            self.switcher.set_current("search")

    def apply_theme(self, palette: dict):
        self.search_tab.apply_theme(palette)
        self.people_tab.apply_theme(palette)
