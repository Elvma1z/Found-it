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
from found_it.gui import ds
from found_it.utils.os_open import open_file, open_containing_folder

IMAGE_FILE_FILTER = "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif)"


class PeopleGalleryWidget(QWidget):
    """Browse the people detected while indexing photos: a gallery of face
    tiles (one per clustered person, named or not) that, when selected,
    shows every photo containing them."""

    _add_person_done = pyqtSignal(object, str)
    _add_file_done = pyqtSignal(bool, int)
    people_count_changed = pyqtSignal(int)

    def __init__(self, engine: FileSearchEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._people: List[dict] = []
        self._person_results: List[SearchResult] = []
        self._setup_ui()
        self._add_person_done.connect(self._on_add_person_done)
        self._add_file_done.connect(self._on_add_file_done)

    def apply_theme(self, palette: dict):
        pass

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # --- People gallery ---
        left = ds.GlassPanel("People", "users")
        self.add_person_btn = ds.Button("Add person", "ghost", "user-plus", size="sm")
        self.add_person_btn.setToolTip("Pick a photo of someone to tag them as a new person")
        self.add_person_btn.clicked.connect(self._add_person)
        left.add_action(self.add_person_btn)
        self.refresh_btn = left.add_icon_button("refresh-cw", "Refresh")
        self.refresh_btn.clicked.connect(lambda: self.refresh())
        lb = left.body_layout
        lb.addWidget(ds.text("Faces found while indexing your photos. Name someone so search can find them.",
                             "small", wrap=True))
        self.people_search = ds.TextInput("Search people...", icon="search", size="sm")
        self.people_search.textChanged.connect(self._filter_people)
        lb.addWidget(self.people_search)
        self.people_list = ds.RowList("No people detected yet. Scan your photos from the Search tab first.",
                                      "users", grid=True)
        self.people_list.currentRowChanged.connect(self._on_person_selected)
        lb.addWidget(self.people_list, 1)
        self.status_label = ds.text("", "caption", wrap=True)
        lb.addWidget(self.status_label)
        layout.addWidget(left, 13)

        # --- Selected person ---
        self.person_panel = ds.GlassPanel("Person", "user")
        self.rename_btn = self.person_panel.add_icon_button("pencil", "Rename")
        self.rename_btn.clicked.connect(self._rename_selected_person)
        self.add_file_btn = self.person_panel.add_icon_button("image-plus", "Add a photo of this person")
        self.add_file_btn.clicked.connect(self._add_file_to_selected_person)
        self.delete_btn = self.person_panel.add_icon_button(
            "trash-2", "Remove this person - their photos stay indexed, just untagged", danger=True)
        self.delete_btn.clicked.connect(self._delete_selected_person)
        for b in (self.rename_btn, self.add_file_btn, self.delete_btn):
            b.setEnabled(False)
        rb = self.person_panel.body_layout

        self.description_search = ds.TextInput('e.g. "Riddeck wearing a blue jacket"', size="sm")
        self.description_search.returnPressed.connect(self._on_description_search)
        self.description_search_btn = ds.Button("Find", "primary", size="sm")
        self.description_search_btn.clicked.connect(self._on_description_search)
        rb.addLayout(ds.hbox(self.description_search, self.description_search_btn, stretch_at=0))
        rb.addWidget(ds.text("Name a person plus what they're wearing or doing to rank their photos.",
                             "caption", wrap=True))
        rb.addWidget(ds.separator())
        self.photos_label = ds.text("", "eyebrow")
        rb.addWidget(self.photos_label)
        self.photos_list = ds.RowList("Select a person to see their photos.", "image")
        self.photos_list.currentRowChanged.connect(self._on_photo_selected)
        rb.addWidget(self.photos_list, 1)

        self.open_btn = ds.Button("Open file", "secondary", "external-link", size="sm")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_photo)
        self.open_dir_btn = ds.Button("Open folder", "ghost", "folder-open", size="sm")
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.clicked.connect(self._open_photo_folder)
        rb.addLayout(ds.hbox(self.open_btn, self.open_dir_btn, None))
        layout.addWidget(self.person_panel, 10)

    def _set_person_actions(self, enabled: bool):
        for b in (self.rename_btn, self.delete_btn, self.add_file_btn):
            b.setEnabled(enabled)

    @staticmethod
    def _display_name(person: dict) -> str:
        return person["name"] or f"Unnamed #{person['id']}"

    def _photo_row(self, result, score=None):
        return ds.make_row("result", icon="image", color="#a78bfa", title=result.name,
                           path=result.path, score=score)

    def refresh(self, select_person_id: Optional[int] = None):
        self._people = self.engine.get_people()
        self.people_list.clear()
        self.photos_list.clear()
        self._person_results = []
        self.photos_label.setText("")
        self.person_panel.set_title("Person")
        self._set_person_actions(False)
        self.open_btn.setEnabled(False)
        self.open_dir_btn.setEnabled(False)

        for person in self._people:
            item = ds.make_row("person", title=self._display_name(person), count=person["face_count"],
                               image=person.get("thumbnail_path"))
            item.setData(Qt.UserRole, person["id"])
            self.people_list.addItem(item)

        self._filter_people(self.people_search.text())

        if not self._people:
            self.status_label.setText("No people detected yet. Scan your photos from the Search tab first.")
        else:
            n = len(self._people)
            self.status_label.setText(f"{n} {'person' if n == 1 else 'people'} detected")
        self.people_count_changed.emit(len(self._people))

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
        self._set_person_actions(True)
        self.person_panel.set_title(person_name)

        self._person_results = results
        self.photos_list.clear()
        for result in results:
            self.photos_list.addItem(self._photo_row(result, result.score))

        if not results:
            self.photos_label.setText("No close matches")
            self.photos_list.set_empty("No photos closely match that description.", "search-x")
            self.status_label.setText("No close matches - try a different description.")
        else:
            self.photos_label.setText(f"{len(results)} match{'es' if len(results) != 1 else ''} for that description")
            self.status_label.setText("")

    def _on_person_selected(self, row):
        self.photos_list.clear()
        self.open_btn.setEnabled(False)
        self.open_dir_btn.setEnabled(False)

        if row < 0 or row >= len(self._people):
            self._set_person_actions(False)
            self.person_panel.set_title("Person")
            self.photos_label.setText("")
            self.photos_list.set_empty("Select a person to see their photos.", "image")
            return

        self._set_person_actions(True)
        person = self._people[row]
        self._person_results = self.engine.get_files_for_person(person["id"])
        display_name = self._display_name(person)
        self.person_panel.set_title(display_name)
        n = len(self._person_results)
        self.photos_label.setText(f"{n} of {person['face_count']} photo{'s' if person['face_count'] != 1 else ''}")
        self.photos_list.set_empty("No photos for this person yet.", "image")

        for result in self._person_results:
            self.photos_list.addItem(self._photo_row(result))

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
