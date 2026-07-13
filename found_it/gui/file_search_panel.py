import os
import subprocess
import platform
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QFileDialog, QProgressBar, QSplitter,
    QTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QIcon
from typing import List

from found_it.fileindex.search import FileSearchEngine, SearchResult


class FileSearchPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = FileSearchEngine()
        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("File Search")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(title)

        desc = QLabel("Describe a file or image to find it on your PC")
        desc.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(desc)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("e.g. 'vacation photo with mountains'")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a3e;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #6c63ff; }
        """)
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        self.search_btn = QPushButton("Search")
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c63ff;
                color: white; border: none;
                border-radius: 4px; padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a52d5; }
        """)
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel("No folders selected")
        self.folder_label.setStyleSheet("color: #888; font-size: 11px;")
        folder_row.addWidget(self.folder_label)

        self.add_folder_btn = QPushButton("+ Add Folder")
        self.add_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3e; color: #aaa;
                border: 1px solid #444; border-radius: 4px;
                padding: 4px 12px; font-size: 11px;
            }
            QPushButton:hover { background-color: #3a3a5e; color: #e0e0e0; }
        """)
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
        layout.addLayout(folder_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1a1a2e; border: 1px solid #333;
                border-radius: 4px; text-align: center; color: #aaa;
                max-height: 20px;
            }
            QProgressBar::chunk { background-color: #6c63ff; border-radius: 3px; }
        """)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.status_label)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #333;")
        layout.addWidget(sep2)

        self.results_label = QLabel("Results")
        self.results_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.results_label)

        content_splitter = QSplitter(Qt.Horizontal)

        self.results_list = QListWidget()
        self.results_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a2e; color: #e0e0e0;
                border: 1px solid #333; border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px; border-bottom: 1px solid #2a2a3e;
            }
            QListWidget::item:selected { background-color: #3a3a5e; }
            QListWidget::item:hover { background-color: #2a2a4e; }
        """)
        self.results_list.currentRowChanged.connect(self._on_result_select)
        content_splitter.addWidget(self.results_list)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)

        self.preview_label = QLabel("Select a result to preview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a2e; color: #ccc;
                border: 1px solid #333; border-radius: 4px;
                padding: 10px; font-size: 12px;
            }
        """)
        right_layout.addWidget(self.preview_label)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open File")
        self.open_btn.setEnabled(False)
        self.open_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3e; color: #aaa;
                border: 1px solid #444; border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #3a3a5e; color: #e0e0e0; }
            QPushButton:disabled { color: #555; }
        """)
        self.open_btn.clicked.connect(self._open_file)
        btn_row.addWidget(self.open_btn)

        self.open_dir_btn = QPushButton("Open Folder")
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3e; color: #aaa;
                border: 1px solid #444; border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #3a3a5e; color: #e0e0e0; }
            QPushButton:disabled { color: #555; }
        """)
        self.open_dir_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self.open_dir_btn)
        right_layout.addLayout(btn_row)

        content_splitter.addWidget(right_panel)
        content_splitter.setSizes([400, 300])

        layout.addWidget(content_splitter)

        self._folders: List[str] = []
        self._results: List[SearchResult] = []

    def _setup_timer(self):
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(500)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder to index")
        if folder and folder not in self._folders:
            self._folders.append(folder)
            names = [os.path.basename(f) for f in self._folders]
            self.folder_label.setText(f"Folders: {', '.join(names)}")

    def _start_scan(self):
        if not self._folders:
            self.status_label.setText("Add folders first!")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.scan_btn.setEnabled(False)

        self.engine.start_indexing(
            self._folders,
            progress_callback=self._on_progress,
            done_callback=self._on_scan_done
        )

    def _on_progress(self, message):
        self.status_label.setText(message)

    def _on_scan_done(self, count):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        stats = self.engine.get_stats()
        self.status_label.setText(
            f"Done! {stats['total']} files found, "
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

    def _show_results(self):
        self.results_list.clear()
        self.results_label.setText(f"Results ({len(self._results)})")

        for i, result in enumerate(self._results):
            type_icon = {"image": "[IMG]", "code": "[CODE]", "text": "[TXT]"}.get(
                result.file_type, "[?]"
            )
            size_kb = result.size_bytes / 1024
            if size_kb > 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb:.0f} KB"

            score_pct = f"{result.score:.0%}"
            text = f"{type_icon} {result.name}\n  {result.path}\n  {size_str} | Match: {score_pct}"

            item = QListWidgetItem(text)
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

        path = self._results[row].path
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _open_folder(self):
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._results):
            return

        path = self._results[row].path
        folder = os.path.dirname(path)
        if platform.system() == "Windows":
            subprocess.run(["explorer", folder])
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])

    def _poll_status(self):
        if self.engine.is_indexing():
            stats = self.engine.get_stats()
            self.status_label.setText(
                f"Indexing... {stats['indexed']}/{stats['total']} files"
            )
