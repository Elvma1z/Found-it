import os
import string
import platform
import threading
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QFileDialog, QProgressBar, QSplitter,
    QInputDialog, QCheckBox, QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from typing import List

from found_it.fileindex.search import FileSearchEngine, SearchResult
from found_it.gui.people_panel import PeopleGalleryWidget
from found_it.gui.icons import get_icon, ICON_SIZE
from found_it.utils.themes import get_palette, widget_qss, repolish
from found_it.utils.os_open import open_file, open_containing_folder


class SearchTab(QWidget):
    """Prompt or upload-an-image search across every indexed file - photos
    of people, scenery, objects, or plain documents - by CLIP visual/text
    similarity. Named people from the People tab are used automatically to
    narrow a query that mentions one of them by name."""

    _image_search_done = pyqtSignal(list, str)

    def __init__(self, engine: FileSearchEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.palette = get_palette("Indigo")
        self._setup_ui()
        self._setup_timer()
        self._image_search_done.connect(self._on_image_search_done)
        self.apply_theme(self.palette)

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.setStyleSheet(widget_qss(palette))
        self.search_btn.setIcon(get_icon("search", "#ffffff"))
        self.image_search_btn.setIcon(get_icon("image", palette["text_dim"]))
        self.add_folder_btn.setIcon(get_icon("plus", palette["text_dim"]))
        self.cancel_scan_btn.setIcon(get_icon("x", "#e57373"))
        self.add_image_btn.setIcon(get_icon("plus", palette["text_dim"]))
        self.open_btn.setIcon(get_icon("file", palette["text_dim"]))
        self.open_dir_btn.setIcon(get_icon("folder-open", palette["text_dim"]))
        self._show_results()
        repolish(self)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Search")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        layout.addWidget(title)

        desc = QLabel("Find people, scenery, items, or files on your PC - describe "
                       "what you're looking for, or upload a picture of it")
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("e.g. 'vacation photo with mountains', or a person's name")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        self.search_btn = QPushButton(" Search")
        self.search_btn.setIconSize(ICON_SIZE)
        self.search_btn.setProperty("cls", "primary")
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)

        self.image_search_btn = QPushButton(" Search by Image")
        self.image_search_btn.setIconSize(ICON_SIZE)
        self.image_search_btn.setProperty("cls", "secondary")
        self.image_search_btn.setToolTip("Pick a picture and find visually similar indexed images")
        self.image_search_btn.clicked.connect(self._search_by_image)
        search_row.addWidget(self.image_search_btn)
        layout.addLayout(search_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        self.full_pc_checkbox = QCheckBox("Scan entire PC (recommended)")
        self.full_pc_checkbox.setChecked(True)
        self.full_pc_checkbox.stateChanged.connect(self._update_folder_label)
        layout.addWidget(self.full_pc_checkbox)

        full_pc_hint = QLabel("Searches every drive on this PC (skipping system/app folders like "
                               "Windows, Program Files, and AppData). Uncheck to scan only specific "
                               "folders you pick below. Photos found here also populate the People tab.")
        full_pc_hint.setProperty("cls", "hint")
        full_pc_hint.setWordWrap(True)
        layout.addWidget(full_pc_hint)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel("")
        self.folder_label.setProperty("cls", "muted")
        folder_row.addWidget(self.folder_label, 1)

        self.add_folder_btn = QPushButton(" Add Folder")
        self.add_folder_btn.setIconSize(ICON_SIZE)
        self.add_folder_btn.setProperty("cls", "secondary")
        self.add_folder_btn.clicked.connect(self._add_folder)
        folder_row.addWidget(self.add_folder_btn)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50; color: white;
                border: none; border-radius: 4px;
                padding: 4px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background-color: #43a047; }
        """)
        self.scan_btn.clicked.connect(self._start_scan)
        folder_row.addWidget(self.scan_btn)

        self.cancel_scan_btn = QPushButton(" Cancel")
        self.cancel_scan_btn.setIconSize(ICON_SIZE)
        self.cancel_scan_btn.setProperty("cls", "destructive")
        self.cancel_scan_btn.setEnabled(False)
        self.cancel_scan_btn.clicked.connect(self._cancel_scan)
        folder_row.addWidget(self.cancel_scan_btn)

        self.add_image_btn = QPushButton(" Add Image")
        self.add_image_btn.setIconSize(ICON_SIZE)
        self.add_image_btn.setProperty("cls", "secondary")
        self.add_image_btn.clicked.connect(self._add_named_image)
        folder_row.addWidget(self.add_image_btn)
        layout.addLayout(folder_row)

        add_image_hint = QLabel('Or add one specific image and give it a name (e.g. "Passport") '
                                 'to jump straight to it later by typing that name. To name a '
                                 'person instead, use the People tab.')
        add_image_hint.setProperty("cls", "hint")
        add_image_hint.setWordWrap(True)
        layout.addWidget(add_image_hint)

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

        self.preview_label = QLabel("Select a result to preview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setProperty("cls", "muted")
        right_layout.addWidget(self.preview_label)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton(" Open File")
        self.open_btn.setIconSize(ICON_SIZE)
        self.open_btn.setEnabled(False)
        self.open_btn.setProperty("cls", "secondary")
        self.open_btn.clicked.connect(self._open_file)
        btn_row.addWidget(self.open_btn)

        self.open_dir_btn = QPushButton(" Open Folder")
        self.open_dir_btn.setIconSize(ICON_SIZE)
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.setProperty("cls", "secondary")
        self.open_dir_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self.open_dir_btn)
        right_layout.addLayout(btn_row)

        content_splitter.addWidget(right_panel)
        content_splitter.setSizes([400, 300])

        layout.addWidget(content_splitter)

        self._folders: List[str] = []
        self._results: List[SearchResult] = []
        self._scan_was_cancelled = False
        self._update_folder_label()

    def _setup_timer(self):
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(500)

    def _get_all_drives(self) -> List[str]:
        """Every locally reachable drive/volume root, so "Scan entire PC" isn't
        limited to just the folders the user thought to add by hand."""
        if platform.system() == "Windows":
            return [f"{letter}:\\" for letter in string.ascii_uppercase
                    if os.path.exists(f"{letter}:\\")]
        return ["/"]

    def _update_folder_label(self):
        extra = f" + {len(self._folders)} extra folder(s)" if self._folders else ""
        if self.full_pc_checkbox.isChecked():
            self.folder_label.setText(f"Scanning: entire PC{extra}")
        elif self._folders:
            names = [os.path.basename(f) or f for f in self._folders]
            self.folder_label.setText(f"Folders: {', '.join(names)}")
        else:
            self.folder_label.setText("No folders selected")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder to index")
        if folder and folder not in self._folders:
            self._folders.append(folder)
            self._update_folder_label()

    def _start_scan(self):
        if self.full_pc_checkbox.isChecked():
            drives = self._get_all_drives()
            roots = drives + [f for f in self._folders if f not in drives]
        else:
            roots = list(self._folders)

        if not roots:
            self.status_label.setText('Add folders first, or check "Scan entire PC".')
            return

        self._scan_was_cancelled = False
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.scan_btn.setEnabled(False)
        self.cancel_scan_btn.setEnabled(True)

        self.engine.start_indexing(
            roots,
            progress_callback=self._on_progress,
            done_callback=self._on_scan_done
        )

    def _cancel_scan(self):
        self._scan_was_cancelled = True
        self.cancel_scan_btn.setEnabled(False)
        self.status_label.setText("Cancelling...")
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
        self.status_label.setText(f'Adding "{name}"...')
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
        self.status_label.setText(message)

    def _on_scan_done(self, count):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.cancel_scan_btn.setEnabled(False)
        stats = self.engine.get_stats()
        prefix = "Cancelled." if self._scan_was_cancelled else "Done!"
        self.status_label.setText(
            f"{prefix} {stats['total']} files found, "
            f"{stats['embedded']} indexed "
            f"({stats['images']} images, {stats['texts']} texts, {stats['codes']} code)"
        )

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        if self.engine.is_indexing():
            self.status_label.setText("Still indexing, please wait...")
            return

        if len(self.engine.store) == 0:
            self.status_label.setText("No files indexed yet. Add folders and scan first.")
            return

        self.status_label.setText(f"Searching for: {query}")
        self._results = self.engine.search(query, top_k=30)
        self._show_results()

    def _search_by_image(self):
        if self.engine.is_indexing():
            self.status_label.setText("Still indexing, please wait...")
            return

        if len(self.engine.store) == 0:
            self.status_label.setText("No files indexed yet. Add folders and scan first.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Select an image to search with",
            "", "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif)"
        )
        if not path:
            return

        self.image_search_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.status_label.setText(f"Searching for images like {os.path.basename(path)}...")

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
                f"No visual matches found for {os.path.basename(path)} "
                "(image search needs open-clip-torch installed)."
            )
        else:
            self.status_label.setText(
                f"Found {len(results)} visual match(es) for {os.path.basename(path)}"
            )
        self._show_results()

    def _show_results(self):
        self.results_list.clear()
        self.results_label.setText(f"Results ({len(self._results)})")

        for i, result in enumerate(self._results):
            icon_name = {"image": "image", "code": "code", "text": "file-text"}.get(
                result.file_type, "file"
            )
            size_kb = result.size_bytes / 1024
            if size_kb > 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb:.0f} KB"

            score_pct = f"{result.score:.0%}"
            text = f"{result.name}\n  {result.path}\n  {size_str} | Match: {score_pct}"

            item = QListWidgetItem(get_icon(icon_name, self.palette["text_dim"]), text)
            item.setData(Qt.UserRole, i)
            self.results_list.addItem(item)

    def _on_result_select(self, row):
        if row < 0 or row >= len(self._results):
            return

        result = self._results[row]

        preview = f"Name: {result.name}\n"
        preview += f"Path: {result.path}\n"
        preview += f"Type: {result.file_type}\n"
        preview += f"Size: {result.size_bytes / 1024:.0f} KB\n"
        preview += f"Match: {result.score:.1%}\n"
        if result.text_preview:
            preview += f"\nPreview:\n{result.text_preview[:500]}"

        self.preview_label.setText(preview)
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
            self.status_label.setText(
                f"Indexing... {stats['indexed']}/{stats['total']} files"
            )


class FileSearchPanel(QWidget):
    """Search mode: a Search tab (prompt or upload-an-image, across photos,
    scenery, items, and files generally) and a People tab (browse/name the
    faces detected while indexing), sharing one underlying search engine
    and index."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = FileSearchEngine()
        self.palette = get_palette("Indigo")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.search_tab = SearchTab(self.engine)
        self.people_tab = PeopleGalleryWidget(self.engine)
        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.people_tab, "People")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        self.apply_theme(self.palette)

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) is self.people_tab:
            self.people_tab.refresh()

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.setStyleSheet(widget_qss(palette))
        repolish(self)
        self.search_tab.apply_theme(palette)
        self.people_tab.apply_theme(palette)
