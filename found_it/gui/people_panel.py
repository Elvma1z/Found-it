import os
import threading
from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QSplitter, QInputDialog, QLineEdit, QFileDialog,
    QMessageBox
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap, QFont

from found_it.fileindex.search import FileSearchEngine, SearchResult
from found_it.gui.icons import get_icon, ICON_SIZE
from found_it.utils.themes import get_palette, widget_qss, repolish
from found_it.utils.os_open import open_file, open_containing_folder

IMAGE_FILE_FILTER = "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif)"


class PeopleGalleryWidget(QWidget):
    """Browse the people detected while indexing photos: a gallery of face
    thumbnails (one per clustered person, named or not) that, when
    selected, shows every photo containing them."""

    _add_person_done = pyqtSignal(object, str)
    _add_file_done = pyqtSignal(bool, int)

    def __init__(self, engine: FileSearchEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.palette = get_palette("Indigo")
        self._people: List[dict] = []
        self._person_results: List[SearchResult] = []
        self._setup_ui()
        self._add_person_done.connect(self._on_add_person_done)
        self._add_file_done.connect(self._on_add_file_done)
        self.apply_theme(self.palette)

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.setStyleSheet(widget_qss(palette))
        self.add_person_btn.setIcon(get_icon("plus", palette["text_dim"]))
        self.add_file_btn.setIcon(get_icon("plus", palette["text_dim"]))
        self.open_btn.setIcon(get_icon("file", palette["text_dim"]))
        self.open_dir_btn.setIcon(get_icon("folder-open", palette["text_dim"]))
        repolish(self)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("People")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        layout.addWidget(title)

        desc = QLabel("Faces found while indexing your photos. Click a person to see "
                       "their photos, or rename them so search can find them by name.")
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        top_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("cls", "secondary")
        self.refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(self.refresh_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        self.status_label = QLabel("")
        self.status_label.setProperty("cls", "hint")
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.people_search = QLineEdit()
        self.people_search.setPlaceholderText("Search people...")
        self.people_search.textChanged.connect(self._filter_people)
        left_layout.addWidget(self.people_search)

        self.people_list = QListWidget()
        self.people_list.setViewMode(QListWidget.IconMode)
        self.people_list.setIconSize(QSize(96, 96))
        self.people_list.setResizeMode(QListWidget.Adjust)
        self.people_list.setMovement(QListWidget.Static)
        self.people_list.setSpacing(10)
        self.people_list.setWordWrap(True)
        self.people_list.currentRowChanged.connect(self._on_person_selected)
        left_layout.addWidget(self.people_list)

        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)

        desc_search_row = QHBoxLayout()
        self.description_search = QLineEdit()
        self.description_search.setPlaceholderText('e.g. "Riddeck wearing a blue jacket"')
        self.description_search.returnPressed.connect(self._on_description_search)
        desc_search_row.addWidget(self.description_search)

        self.description_search_btn = QPushButton("Find")
        self.description_search_btn.setProperty("cls", "primary")
        self.description_search_btn.clicked.connect(self._on_description_search)
        desc_search_row.addWidget(self.description_search_btn)
        right_layout.addLayout(desc_search_row)

        desc_search_hint = QLabel("Name a person plus what they're wearing or doing, and their "
                                   "photos are ranked by the closest match.")
        desc_search_hint.setProperty("cls", "hint")
        desc_search_hint.setWordWrap(True)
        right_layout.addWidget(desc_search_hint)

        rename_row = QHBoxLayout()
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setProperty("cls", "secondary")
        self.rename_btn.setEnabled(False)
        self.rename_btn.clicked.connect(self._rename_selected_person)
        rename_row.addWidget(self.rename_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("cls", "secondary")
        self.delete_btn.setEnabled(False)
        self.delete_btn.setToolTip("Remove this person - their photos stay indexed, just untagged")
        self.delete_btn.clicked.connect(self._delete_selected_person)
        rename_row.addWidget(self.delete_btn)

        self.add_person_btn = QPushButton(" Add Person")
        self.add_person_btn.setIconSize(ICON_SIZE)
        self.add_person_btn.setProperty("cls", "secondary")
        self.add_person_btn.setToolTip("Pick a photo of someone to tag them as a new person")
        self.add_person_btn.clicked.connect(self._add_person)
        rename_row.addWidget(self.add_person_btn)

        self.add_file_btn = QPushButton(" Add File")
        self.add_file_btn.setIconSize(ICON_SIZE)
        self.add_file_btn.setProperty("cls", "secondary")
        self.add_file_btn.setEnabled(False)
        self.add_file_btn.setToolTip("Pick another photo of the selected person to add to their gallery")
        self.add_file_btn.clicked.connect(self._add_file_to_selected_person)
        rename_row.addWidget(self.add_file_btn)

        rename_row.addStretch()
        right_layout.addLayout(rename_row)

        self.photos_label = QLabel("Select a person to see their photos")
        self.photos_label.setProperty("cls", "muted")
        right_layout.addWidget(self.photos_label)

        self.photos_list = QListWidget()
        self.photos_list.currentRowChanged.connect(self._on_photo_selected)
        right_layout.addWidget(self.photos_list)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton(" Open File")
        self.open_btn.setIconSize(ICON_SIZE)
        self.open_btn.setEnabled(False)
        self.open_btn.setProperty("cls", "secondary")
        self.open_btn.clicked.connect(self._open_photo)
        btn_row.addWidget(self.open_btn)

        self.open_dir_btn = QPushButton(" Open Folder")
        self.open_dir_btn.setIconSize(ICON_SIZE)
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.setProperty("cls", "secondary")
        self.open_dir_btn.clicked.connect(self._open_photo_folder)
        btn_row.addWidget(self.open_dir_btn)
        right_layout.addLayout(btn_row)

        splitter.addWidget(right_panel)
        splitter.setSizes([420, 300])
        layout.addWidget(splitter)

    def refresh(self, select_person_id: Optional[int] = None):
        self._people = self.engine.get_people()
        self.people_list.clear()
        self.photos_list.clear()
        self._person_results = []
        self.photos_label.setText("Select a person to see their photos")
        self.rename_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.add_file_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.open_dir_btn.setEnabled(False)

        for person in self._people:
            display_name = person["name"] or f"Unnamed #{person['id']}"
            item = QListWidgetItem(f"{display_name}\n({person['face_count']} photo(s))")
            item.setData(Qt.UserRole, person["id"])
            thumb = person.get("thumbnail_path")
            if thumb and os.path.exists(thumb):
                item.setIcon(QIcon(QPixmap(thumb)))
            item.setTextAlignment(Qt.AlignHCenter)
            self.people_list.addItem(item)

        self._filter_people(self.people_search.text())

        if not self._people:
            self.status_label.setText("No people detected yet. Scan your photos from the Search tab first.")
        else:
            self.status_label.setText(f"{len(self._people)} person/people detected")

        if select_person_id is not None:
            for i, person in enumerate(self._people):
                if person["id"] == select_person_id:
                    self.people_list.setCurrentRow(i)
                    break

    def _filter_people(self, text: str):
        query = text.strip().lower()
        for i in range(self.people_list.count()):
            item = self.people_list.item(i)
            person_id = item.data(Qt.UserRole)
            person = next((p for p in self._people if p["id"] == person_id), None)
            display_name = (person["name"] or f"Unnamed #{person['id']}").lower() if person else ""
            item.setHidden(bool(query) and query not in display_name)

    def _on_description_search(self):
        query = self.description_search.text().strip()
        if not query:
            return

        self.status_label.setText(f"Searching: {query}")
        outcome = self.engine.search_person_by_description(query, top_k=30)
        if outcome is None:
            self.status_label.setText(
                'No named person found in that search - rename someone first, then try '
                'e.g. "Riddeck wearing a blue jacket".'
            )
            return

        person_id, person_name, results = outcome

        # Sync the left-hand selection so Rename/+Add File apply to the
        # right person, without letting the selection change stomp the
        # ranked results we're about to show (currentRowChanged would
        # otherwise repopulate photos_list with that person's full,
        # unranked photo list).
        self.people_list.blockSignals(True)
        for i, person in enumerate(self._people):
            if person["id"] == person_id:
                self.people_list.setCurrentRow(i)
                break
        self.people_list.blockSignals(False)
        self.rename_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.add_file_btn.setEnabled(True)

        self._person_results = results
        self.photos_list.clear()
        for result in results:
            item = QListWidgetItem(f"{result.name}\n  {result.path}\n  Match: {result.score:.0%}")
            self.photos_list.addItem(item)

        if not results:
            self.photos_label.setText(f"{person_name}: no photos closely match that description")
            self.status_label.setText("No close matches - try a different description")
        else:
            self.photos_label.setText(f'{person_name}: {len(results)} match(es) for that description')
            self.status_label.setText(f"Found {len(results)} match(es)")

    def _on_person_selected(self, row):
        self.photos_list.clear()
        self.open_btn.setEnabled(False)
        self.open_dir_btn.setEnabled(False)

        if row < 0 or row >= len(self._people):
            self.rename_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.add_file_btn.setEnabled(False)
            self.photos_label.setText("Select a person to see their photos")
            return

        self.rename_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.add_file_btn.setEnabled(True)
        person = self._people[row]
        self._person_results = self.engine.get_files_for_person(person["id"])
        display_name = person["name"] or f"Unnamed #{person['id']}"
        self.photos_label.setText(f"{display_name}: {len(self._person_results)} photo(s)")

        for result in self._person_results:
            item = QListWidgetItem(f"{result.name}\n  {result.path}")
            self.photos_list.addItem(item)

    def _on_photo_selected(self, row):
        enabled = 0 <= row < len(self._person_results)
        self.open_btn.setEnabled(enabled)
        self.open_dir_btn.setEnabled(enabled)

    def _rename_selected_person(self):
        row = self.people_list.currentRow()
        if row < 0 or row >= len(self._people):
            return
        person = self._people[row]
        name, ok = QInputDialog.getText(
            self, "Name this person", "Name:", text=person["name"] or ""
        )
        if not ok or not name.strip():
            return
        self.engine.rename_person(person["id"], name.strip())
        self.refresh(select_person_id=person["id"])

    def _delete_selected_person(self):
        row = self.people_list.currentRow()
        if row < 0 or row >= len(self._people):
            return
        person = self._people[row]
        display_name = person["name"] or f"Unnamed #{person['id']}"

        confirm = QMessageBox.question(
            self, "Delete person",
            f'Remove "{display_name}" from People? Their {person["face_count"]} photo(s) '
            'stay indexed and searchable - they just won\'t be tagged as this person anymore.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        self.engine.delete_person(person["id"])
        self.status_label.setText(f'Deleted "{display_name}".')
        self.refresh()

    def _add_person(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a photo of the person", "", IMAGE_FILE_FILTER
        )
        if not path:
            return

        default_name = os.path.splitext(os.path.basename(path))[0]
        name, ok = QInputDialog.getText(
            self, "Name this person", "Name:", text=default_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        self.add_person_btn.setEnabled(False)
        self.status_label.setText(f'Looking for a face in the photo to tag as "{name}"...')

        def worker():
            person_id = self.engine.add_person_from_image(path, name)
            self._add_person_done.emit(person_id, name)

        threading.Thread(target=worker, daemon=True).start()

    def _on_add_person_done(self, person_id, name: str):
        self.add_person_btn.setEnabled(True)
        if person_id is None:
            self.status_label.setText(f'No face found in that photo - couldn\'t tag "{name}".')
            return
        self.status_label.setText(f'Added "{name}".')
        self.refresh(select_person_id=person_id)

    def _add_file_to_selected_person(self):
        row = self.people_list.currentRow()
        if row < 0 or row >= len(self._people):
            return
        person = self._people[row]

        path, _ = QFileDialog.getOpenFileName(
            self, "Select a photo to add", "", IMAGE_FILE_FILTER
        )
        if not path:
            return

        display_name = person["name"] or f"Unnamed #{person['id']}"
        self.add_file_btn.setEnabled(False)
        self.status_label.setText(f"Adding photo to {display_name}...")

        def worker():
            success = self.engine.add_file_to_person(path, person["id"])
            self._add_file_done.emit(success, person["id"])

        threading.Thread(target=worker, daemon=True).start()

    def _on_add_file_done(self, success: bool, person_id: int):
        self.add_file_btn.setEnabled(True)
        if success:
            self.status_label.setText("Photo added.")
        else:
            self.status_label.setText("No face found in that photo - couldn't add it.")
        self.refresh(select_person_id=person_id)

    def _open_photo(self):
        row = self.photos_list.currentRow()
        if row < 0 or row >= len(self._person_results):
            return
        open_file(self._person_results[row].path)

    def _open_photo_folder(self):
        row = self.photos_list.currentRow()
        if row < 0 or row >= len(self._person_results):
            return
        open_containing_folder(self._person_results[row].path)
