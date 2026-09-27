from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from found_it.config import CAMERA_LABELS
from found_it.gui import ds
from found_it.utils.themes import pin_color


def _last_seen_time(item: dict) -> str:
    return (item.get("last_seen") or "")[11:16]


class SearchPanel(QWidget):
    """Room Tracker's "Found items" panel body (components: TextInput,
    ResultRow list, DetailList card)."""

    item_selected = pyqtSignal(dict)
    selection_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self._room_names: dict = {}
        self._all_items: List[dict] = []
        self._shown: List[dict] = []
        self._query = ""
        self._selected_id = None
        self._setup_ui()

    def set_room_names(self, room_names: dict):
        """room_id -> room name, so results can show which tracked room an item was found in."""
        self._room_names = room_names

    def apply_theme(self, palette: dict):
        pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.search_input = ds.TextInput("Where are my keys?", icon="search", hint="↵")
        self.search_input.returnPressed.connect(self._on_search)
        self.search_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search_input)

        self.results_label = ds.text("All detected items · 0", "eyebrow")
        self.results_label.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.results_label)

        self.results_list = ds.RowList("Nothing has been detected yet", "search-x")
        self.results_list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.results_list, 1)

        self.detail_card = ds.Card(14, 12)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.detail_title = ds.text("", "h3")
        head.addWidget(self.detail_title, 1)
        clear_btn = ds.IconButton("x", "Clear", "sm")
        clear_btn.clicked.connect(self.clear_selection)
        head.addWidget(clear_btn)
        self.detail_card.layout_.addLayout(head)
        self.detail_list = ds.DetailList()
        self.detail_card.layout_.addWidget(self.detail_list)
        self.detail_card.hide()
        layout.addWidget(self.detail_card)

        self.detail_hint = ds.text("Select an item to see where and when it was last seen.", "caption", wrap=True)
        self.detail_hint.setContentsMargins(4, 4, 4, 2)
        layout.addWidget(self.detail_hint)

        # Kept so the previous Details label stays addressable by older code.
        self.detail_label = self.detail_hint

    # ---------------------------------------------------------------- data

    def _on_text_changed(self, text: str):
        if not text.strip() and self._query:
            self._query = ""
            self._render()

    def _on_search(self):
        query = self.search_input.text().strip()
        self._query = query
        self._render()

    def _matching(self) -> List[dict]:
        if not self._query:
            return list(self._all_items)
        from found_it.storage.database import Database
        db = Database()
        results = db.find_items(self._query)
        db.close()
        return results

    def show_all_items(self, items: List[dict]):
        self._all_items = items
        self._render()

    def _render(self):
        self._shown = self._matching()
        if self._query:
            self.results_label.setText(f'RESULTS FOR "{self._query.upper()}" · {len(self._shown)}')
            self.results_list.set_empty(f'Nothing called "{self._query}" has been seen yet', "search-x")
        else:
            self.results_label.setText(f"ALL DETECTED ITEMS · {len(self._shown)}")
            self.results_list.set_empty("Nothing has been detected yet", "search-x")

        lst = self.results_list
        lst.blockSignals(True)
        scroll = lst.verticalScrollBar().value()
        lst.clear()
        reselect = None
        for item in self._shown:
            row = ds.make_row(
                "result", icon="map-pin", color=pin_color(item.get("camera_id", 0)),
                title=item.get("label", "unknown"), subtitle=self._subtitle(item),
                score=item.get("confidence", 0),
            )
            row.setData(Qt.UserRole, item)
            lst.addItem(row)
            if self._selected_id is not None and item.get("id") == self._selected_id:
                reselect = row
        if reselect is not None:
            lst.setCurrentItem(reselect)
            self._show_details(reselect.data(Qt.UserRole))
        lst.verticalScrollBar().setValue(scroll)
        lst.blockSignals(False)

    def _room_name(self, item: dict) -> str:
        return self._room_names.get(item.get("room_id"), item.get("room_id") or "Unknown room")

    def _subtitle(self, item: dict) -> str:
        zone = item.get("zone_name")
        zone = f"{zone[0].upper()}{zone[1:]}" if zone else "Unmarked area"
        parts = [zone, self._room_name(item), _last_seen_time(item)]
        return " · ".join(x for x in parts if x)

    # ---------------------------------------------------------------- selection

    def _on_current_changed(self, current, _previous):
        if current is None:
            return
        data = current.data(Qt.UserRole)
        if data:
            self._selected_id = data.get("id")
            self._show_details(data)
            self.item_selected.emit(data)

    def select_item(self, item: dict):
        """Select `item` (e.g. from a click on its map pin)."""
        self._selected_id = item.get("id")
        for i in range(self.results_list.count()):
            row = self.results_list.item(i)
            data = row.data(Qt.UserRole) or {}
            if data.get("id") == self._selected_id:
                self.results_list.setCurrentItem(row)
                return
        self._show_details(item)
        self.item_selected.emit(item)

    def clear_selection(self):
        self._selected_id = None
        self.results_list.blockSignals(True)
        self.results_list.setCurrentRow(-1)
        self.results_list.clearSelection()
        self.results_list.blockSignals(False)
        self.detail_card.hide()
        self.detail_hint.show()
        self.selection_cleared.emit()

    def _show_details(self, item: dict):
        cam = item.get("camera_id", 0)
        zone = item.get("zone_name")
        zone = f"{zone[0].upper()}{zone[1:]}" if zone else "Unmarked area"
        first = (item.get("first_seen") or "")[:16].replace("T", " ")
        last = (item.get("last_seen") or "")[:16].replace("T", " ")
        self.detail_title.setText(item.get("label", "unknown"))
        self.detail_list.set_items([
            ("Location", f"{zone}, {self._room_name(item)}"),
            ("Camera", CAMERA_LABELS.get(cam, f"Camera {cam}")),
            ("Confidence", f"{item.get('confidence', 0) * 100:.1f}%"),
            ("Position", f"({item.get('zone_x', 0):.2f}, {item.get('zone_y', 0):.2f})", True),
            ("First seen", first),
            ("Last seen", last),
        ])
        self.detail_card.show()
        self.detail_hint.hide()
