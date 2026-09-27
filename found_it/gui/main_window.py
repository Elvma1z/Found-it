import json
import os
import time

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QCheckBox, QTabWidget,
    QPushButton, QMenu, QDockWidget, QComboBox, QApplication,
    QGraphicsDropShadowEffect, QShortcut
)
from PyQt5.QtCore import Qt, QTimer, QThread, QByteArray, QEvent, QSize, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QKeySequence, QPixmap

NAV_TAB_KEYS_DEFAULT = ["room", "room_setup", "file", "device"]
DOCK_PANEL_KEYS_DEFAULT = ["camera_dock", "found_items_dock"]

# Panels are pinned where they are in the live app: no Movable (drag to a
# different edge), no Floatable (tear off into its own window). Rearranging
# them is done deliberately, in Settings > Customization, against a preview -
# so an accidental drag on the title bar can't scramble the workspace.
# Closable stays on so a panel can still be hidden and brought back from the
# View menu, which doesn't change where anything sits.
LOCKED_DOCK_FEATURES = QDockWidget.DockWidgetClosable


class ClickableLabel(QLabel):
    """A QLabel that emits clicked() and swallows the press so it doesn't
    also trigger the parent TitleBar's window-drag handling."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TitleBar(QWidget):
    """The nav bar doubles as the window's title bar: dragging empty space
    on it moves the (frameless) window, double-clicking toggles maximize."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            window = self.window()
            if window.isMaximized():
                window.showNormal()
            else:
                window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

from found_it.config import ITEM_INACTIVE_SECONDS
from found_it.camera.capture import CameraCapture
from found_it.camera.dewarp import FisheyeDewarp, EquirectangularDewarp
from found_it.detection.detector import ItemDetector
from found_it.detection.item_mapper import ItemMapper
from found_it.storage.database import Database
from found_it.storage.models import DetectedItem
from found_it.utils.room_profiles import load_room_profiles
from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.themes import get_palette, repolish, pin_color, theme_parts, theme_name
from found_it.utils.saved_devices import load_saved_devices
from found_it.utils.resources import ICON_PATH
from found_it.gui.icons import get_icon, ICON_SIZE
from found_it.gui.help_info import HelpInfoMixin
from found_it.gui import ds
from found_it.gui.command_palette import CommandPalette, PaletteEntry
from found_it.gui.camera_view import CameraSpotlight, CameraView
from found_it.gui.room_map import RoomMap
from found_it.gui.search_panel import SearchPanel
from found_it.gui.file_search_panel import FileSearchPanel
from found_it.gui.device_search_panel import DeviceSearchPanel
from found_it.gui.room_setup_panel import RoomSetupPanel
from found_it.gui.settings_panel import SettingsPanel
from found_it.gui.camera_settings_panel import CameraSettingsPanel
from found_it.gui.detection_worker import DetectionWorker
from found_it.gui.welcome import TutorialDialog, WhatsNewDialog, pending_startup
from found_it.version import APP_VERSION, current_release


class MainWindow(QMainWindow, HelpInfoMixin):
    def __init__(self):
        super().__init__()
        self._init_help_info()
        self.setWindowTitle("Found It")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(1280, 700)
        self.resize(1400, 800)

        self._binding_shortcut = False

        self.room_profiles = load_room_profiles()
        self.app_settings = load_app_settings()
        self.palette = get_palette(self.app_settings.theme)
        self.active_room_id = self._resolve_active_room_id()
        self.db = Database()
        self.detector = ItemDetector(self.app_settings.detection_model)
        self.room_mappers = {}
        self.room_cameras = {}
        self.room_dewarpers = {}
        self.cam_views = {}
        self._tracked_item_id = None
        self._tracked_view = None
        self._current_mode = "room"

        self._setup_ui()
        self._setup_timers()
        self._start_all_room_cameras()

    def _get_profile(self, room_id):
        return next((p for p in self.room_profiles if p.id == room_id), None)

    def _resolve_active_room_id(self) -> str:
        if any(p.id == self.app_settings.active_room_id for p in self.room_profiles):
            return self.app_settings.active_room_id
        return self.room_profiles[0].id

    def _nav_tab(self, label: str, icon_name: str, mode: str) -> QPushButton:
        """components/navigation/NavTab - icon + label, surface-3 fill and an
        accent icon when active."""
        btn = QPushButton(label)
        btn.setProperty("cls", "navtab")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIconSize(QSize(16, 16))
        btn.clicked.connect(lambda: self._switch_mode(mode))
        btn._icon_name = icon_name
        btn.toggled.connect(lambda _c, b=btn: self._tint_nav_tab(b))
        return btn

    def _tint_nav_tab(self, btn: QPushButton):
        p = ds.pal()
        btn.setIcon(get_icon(btn._icon_name, p["accent_text"] if btn.isChecked() else p["text2"], 16))

    def _setup_ui(self):
        central = ds.GlowBackdrop()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Title bar (components/navigation/TitleBar) ---
        self.nav_bar = TitleBar()
        self.nav_bar.setObjectName("titleBar")
        self.nav_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.nav_bar.setFixedHeight(52)
        bar = QHBoxLayout(self.nav_bar)
        bar.setContentsMargins(14, 0, 0, 0)
        bar.setSpacing(4)

        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(22, 22)
        icon_pm = QPixmap(str(ICON_PATH)).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_pm.setDevicePixelRatio(2)
        self.brand_icon.setPixmap(icon_pm)
        bar.addWidget(self.brand_icon)
        bar.addSpacing(5)
        self.app_title = ClickableLabel("Found It")
        self.app_title.setStyleSheet(
            'font-family: "Segoe UI"; font-size: 15px; font-weight: 700;')
        self.app_title.clicked.connect(self._on_title_clicked)
        bar.addWidget(self.app_title)
        bar.addSpacing(18)

        self.mode_room_btn = self._nav_tab("Room Tracker", "scan-eye", "room")
        self.mode_room_setup_btn = self._nav_tab("Room Setup", "pencil-ruler", "room_setup")
        self.mode_cameras_btn = self._nav_tab("Cameras", "cctv", "cameras")
        self.mode_file_btn = self._nav_tab("File Search", "folder-search", "file")
        self.mode_device_btn = self._nav_tab("Other Devices", "smartphone", "device")
        self.mode_room_btn.setChecked(True)
        self.nav_mode_buttons = {
            "room": self.mode_room_btn,
            "room_setup": self.mode_room_setup_btn,
            "file": self.mode_file_btn,
            "device": self.mode_device_btn,
        }
        self.nav_layout = QHBoxLayout()
        self.nav_layout.setSpacing(2)
        self._nav_tabs_insert_index = 0
        bar.addLayout(self.nav_layout)
        self._apply_nav_tab_order()
        bar.addStretch(1)

        self.search_pill = QPushButton("Search everything")
        self.search_pill.setObjectName("searchTrigger")
        self.search_pill.setFixedWidth(260)
        self.search_pill.setCursor(Qt.PointingHandCursor)
        self.search_pill.clicked.connect(self.open_palette)
        pill = QHBoxLayout(self.search_pill)
        pill.setContentsMargins(10, 0, 6, 0)
        pill.setSpacing(4)
        pill.addWidget(ds.IconLabel("search", "text3", 15))
        pill.addStretch(1)
        pill.addWidget(ds.Kbd("Ctrl"))
        pill.addWidget(ds.Kbd("K"))
        for child in self.search_pill.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        bar.addWidget(self.search_pill)
        bar.addSpacing(6)

        self.settings_btn = ds.IconButton("settings", "Settings", "md", checkable=True)
        self.settings_btn.clicked.connect(lambda: self._switch_mode("settings"))
        bar.addWidget(self.settings_btn)
        bar.addSpacing(10)

        self.minimize_btn = self._window_button("minus", "Minimize", self.showMinimized)
        self.maximize_btn = self._window_button("square", "Maximize", self._toggle_maximize)
        self.close_btn = self._window_button("x", "Close", self.close, close=True)
        for b in (self.minimize_btn, self.maximize_btn, self.close_btn):
            bar.addWidget(b)
        main_layout.addWidget(self.nav_bar)

        # --- Screens ---
        self.content_stack = QWidget()
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.room_widget = self._build_room_view()
        self.room_setup_panel = RoomSetupPanel()
        self.room_setup_panel.room_updated.connect(self._on_room_updated)
        self.room_setup_panel.manage_cameras_requested.connect(lambda: self._switch_mode("cameras"))
        self.file_search_panel = FileSearchPanel()
        self.device_search_panel = DeviceSearchPanel()
        self.camera_settings_panel = CameraSettingsPanel()
        self.camera_settings_panel.settings_updated.connect(self._on_camera_settings_updated)
        self.settings_panel = SettingsPanel()
        self.settings_panel.settings_updated.connect(self._on_settings_updated)
        self.settings_panel.connect_device_requested.connect(self._on_connect_saved_device)
        self.settings_panel.rooms_imported.connect(self._on_rooms_imported)
        self.settings_panel.find_shortcut_requested.connect(self.start_shortcut_binding)
        self.settings_panel.tutorial_requested.connect(self.show_tutorial)
        self.settings_panel.whats_new_requested.connect(self.show_whats_new)

        for screen in (self.room_widget, self.room_setup_panel, self.file_search_panel,
                       self.device_search_panel, self.camera_settings_panel, self.settings_panel):
            self.content_layout.addWidget(screen)
        for screen in (self.room_setup_panel, self.file_search_panel, self.device_search_panel,
                       self.camera_settings_panel, self.settings_panel):
            screen.hide()
        main_layout.addWidget(self.content_stack, 1)

        # --- Status strip (components/layout/StatusBar) ---
        self.status_strip = ds.StatusStrip()
        self.status_strip.right.setText("Ctrl K to search everything")
        main_layout.addWidget(self.status_strip)

        # Created before the palette so Ctrl+K still opens on top of it.
        self.camera_spotlight = CameraSpotlight(central)
        self.palette_dialog = CommandPalette(central)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)

        self._apply_theme()
        self._update_mode_status()

    def statusBar(self):
        """The design's status strip stands in for QMainWindow's status bar,
        so existing `statusBar().showMessage(...)` calls keep working."""
        return self.status_strip

    def _window_button(self, icon_name: str, tooltip: str, slot, close: bool = False) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("cls", "winbtn")
        if close:
            btn.setProperty("close", "true")
        btn.setFixedSize(46, 52)
        btn.setIconSize(QSize(15, 15))
        btn.setToolTip(tooltip)
        btn._icon_name = icon_name
        btn._close = close
        btn.clicked.connect(slot)
        btn.installEventFilter(self)
        return btn

    def _tint_window_button(self, btn: QPushButton, hover: bool = False):
        p = ds.pal()
        color = "#ffffff" if (hover and btn._close) else p["text3"]
        btn.setIcon(get_icon(btn._icon_name, color, 15))

    def _apply_theme(self):
        p = self.palette
        ds.apply_app_theme(p, self.app_settings.font_family)
        for btn in list(self.nav_mode_buttons.values()) + [self.mode_cameras_btn]:
            self._tint_nav_tab(btn)
        for btn in (self.minimize_btn, self.maximize_btn, self.close_btn):
            self._tint_window_button(btn)
        self._refresh_title_hotkey()
        # Panels that still paint or style parts themselves.
        self.room_setup_panel.apply_theme(p)
        self.file_search_panel.apply_theme(p)
        self.device_search_panel.apply_theme(p)
        self.camera_settings_panel.apply_theme(p)
        self.settings_panel.apply_theme(p)
        self._apply_help_theme(p)

    def _build_room_view(self):
        tracker = QMainWindow()
        tracker.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks)
        tracker.setContentsMargins(12, 12, 12, 12)
        active_profile = self._get_profile(self.active_room_id)

        # --- Cameras panel: position fixed, see LOCKED_DOCK_FEATURES ---
        self.camera_panel = ds.GlassPanel("Cameras", "cctv")
        body = self.camera_panel.body_layout

        self.cam_switcher_holder = QHBoxLayout()
        self.cam_switcher_holder.setSpacing(0)
        self.cam_switcher_holder.addStretch(1)
        body.addLayout(self.cam_switcher_holder)
        self.cam_switcher = None

        # The QTabWidget still owns the camera views (other code indexes into
        # it); its own tab bar is hidden in favour of the segmented switcher.
        self.cam_tabs = QTabWidget()
        self.cam_tabs.tabBar().hide()
        self.cam_tabs.setDocumentMode(True)
        self.cam_tabs.currentChanged.connect(self._sync_cam_switcher)
        body.addWidget(self.cam_tabs)

        self.dewarp_check = ds.Switch("Dewarp")
        self.dewarp_check.setChecked(self.app_settings.dewarp_default)
        body.addWidget(self.dewarp_check)
        self.detection_caption = ds.text("", "caption", wrap=True)
        body.addWidget(self.detection_caption)
        self._add_help(
            None,
            "\"Dewarp\" straightens the fisheye/360° curve out of a camera's raw feed "
            "so straight lines in the room look straight here too.",
            layout=body,
        )
        body.addStretch(1)

        # Kept for the room menu / shortcut code; the map header's room picker
        # is the visible control now.
        self.main_room_btn = QPushButton(active_profile.name)
        self.main_room_btn.clicked.connect(self._show_room_menu)
        self.main_room_btn.hide()

        self.camera_dock = QDockWidget("Cameras", tracker)
        self.camera_dock.setObjectName("camera_dock")
        self.camera_dock.setWidget(self.camera_panel)
        self.camera_dock.setTitleBarWidget(self._empty_title())
        self.camera_dock.setFeatures(LOCKED_DOCK_FEATURES)
        self.camera_panel.setMinimumWidth(280)
        tracker.addDockWidget(Qt.LeftDockWidgetArea, self.camera_dock)
        self.camera_panel.add_icon_button(
            "maximize-2", "Enlarge camera (or double-click a feed)").clicked.connect(
            self._open_current_camera_spotlight)
        self.camera_panel.add_icon_button("x", "Hide cameras").clicked.connect(self.camera_dock.hide)

        # --- Found items panel: position fixed, see LOCKED_DOCK_FEATURES ---
        self.search_panel = SearchPanel()
        self.search_panel.item_selected.connect(self._on_item_selected)
        self.search_panel.selection_cleared.connect(self._on_item_selection_cleared)
        self.search_panel.set_room_names({p.id: p.name for p in self.room_profiles})

        self.found_panel = ds.GlassPanel("Found items", "map-pin", padding=0)
        self.found_panel.body_layout.addWidget(self.search_panel)
        self.found_panel.setMinimumWidth(340)

        self.found_items_dock = QDockWidget("Found Items", tracker)
        self.found_items_dock.setObjectName("found_items_dock")
        self.found_items_dock.setWidget(self.found_panel)
        self.found_items_dock.setTitleBarWidget(self._empty_title())
        self.found_items_dock.setFeatures(LOCKED_DOCK_FEATURES)
        tracker.addDockWidget(Qt.RightDockWidgetArea, self.found_items_dock)
        self.found_panel.add_icon_button("x", "Hide found items").clicked.connect(self.found_items_dock.hide)

        # --- Room map: fixed central area ---
        self.map_panel = ds.GlassPanel("Room map", "map", padding=0)
        self.map_title = self.map_panel.title_label
        self.status_indicator = ds.Badge("Tracking 0 items · 0 rooms", "success", dot=True)
        self.map_panel.add_title_widget(self.status_indicator)

        self.room_map_selector = ds.Select(icon="house", size="sm")
        self.room_map_selector.setFixedWidth(170)
        self._refresh_room_map_selector()
        self.room_map_selector.currentIndexChanged.connect(self._on_room_map_selector_changed)
        self.map_panel.add_action(self.room_map_selector)

        self.toggle_cameras_btn = self._dock_toggle_button(
            "panel-left", "Toggle cameras", self.camera_dock)
        self.toggle_found_btn = self._dock_toggle_button(
            "panel-right", "Toggle found items", self.found_items_dock)
        self.map_panel.add_action(self._make_info_toggle())
        self._add_help(
            None,
            "This map tracks items live across every camera in the room. Pick "
            "an item in \"Found items\" (or click its pin) to highlight its "
            "last known spot here.",
            layout=self.map_panel.body_layout,
        )

        self.room_map = ds_room_map = RoomMap()
        ds_room_map.item_clicked.connect(self.search_panel.select_item)
        self.room_map.set_room_size(active_profile.width_m, active_profile.height_m)
        self.room_map.set_zones(active_profile.zones)
        self.room_map.set_cameras(active_profile.cameras)
        self.map_panel.body_layout.addWidget(self.room_map, 1)

        tracker.setCentralWidget(self.map_panel)
        self.room_widget = tracker

        self._restore_room_tracker_layout(tracker)
        # Applied *after* the restore, not before: the saved state describes
        # wherever the docks last sat, which for a layout saved back when they
        # were draggable can contradict - or float away from - the arrangement
        # set in Customization. Customization is the only way to move panels
        # now, so it gets the last word and the restore only carries sizes.
        self._apply_dock_panel_order()
        tracker.resizeDocks([self.camera_dock, self.found_items_dock], [300, 360], Qt.Horizontal)

        return tracker

    def _rebuild_cam_switcher(self):
        if self.cam_switcher is not None:
            self.cam_switcher.setParent(None)
            self.cam_switcher.deleteLater()
            self.cam_switcher = None
        tabs = [(str(i), self.cam_tabs.tabText(i)) for i in range(self.cam_tabs.count())]
        if not tabs:
            return
        self.cam_switcher = ds.SegmentedTabs(tabs)
        self.cam_switcher.changed.connect(lambda key: self.cam_tabs.setCurrentIndex(int(key)))
        self.cam_switcher_holder.insertWidget(0, self.cam_switcher)
        self._sync_cam_switcher(self.cam_tabs.currentIndex())

    def _open_current_camera_spotlight(self):
        view = self.cam_tabs.currentWidget()
        if isinstance(view, CameraView):
            self._open_camera_spotlight(view.camera_id)

    def _open_camera_spotlight(self, cam_id: int):
        """Give a camera primary view - enlarged over the whole UI."""
        view = self.cam_views.get(cam_id)
        if view is not None:
            self.camera_spotlight.open_for(view)

    def _sync_cam_switcher(self, index: int):
        if self.cam_switcher is not None and index >= 0:
            self.cam_switcher.set_current(str(index))

    def _update_detection_caption(self):
        s = self.app_settings
        self.detection_caption.setText(
            f"Detection runs every {s.detection_frame_skip} frames at "
            f"{s.detection_confidence * 100:.0f}% confidence. Change this in Settings → Camera."
        )

    @staticmethod
    def _empty_title() -> QWidget:
        """Hides a QDockWidget's native title bar - the GlassPanel inside
        draws its own header."""
        w = QWidget()
        w.setFixedHeight(0)
        return w

    def _dock_toggle_button(self, icon_name: str, tooltip: str, dock: QDockWidget) -> ds.IconButton:
        btn = ds.IconButton(icon_name, tooltip, "sm", checkable=True)
        action = dock.toggleViewAction()
        btn.setChecked(action.isChecked())
        btn.clicked.connect(action.trigger)
        action.toggled.connect(btn.setChecked)
        self.map_panel.add_action(btn)
        return btn

    def _on_item_selection_cleared(self):
        self.room_map.set_selected_item(None)
        if self._tracked_view is not None:
            self._tracked_view.clear_highlight()
        self._tracked_item_id = None
        self._tracked_view = None

    def open_palette(self):
        groups = []
        items = []
        for item in self.db.get_active_items():
            room = next((r.name for r in self.room_profiles if r.id == item.get("room_id")), "")
            zone = item.get("zone_name") or "Unmarked area"
            when = (item.get("last_seen") or "")[11:16]
            sub = " · ".join(x for x in (zone, room, when) if x)
            items.append(PaletteEntry(
                "Room items", item.get("label", "item"), sub, "map-pin",
                lambda it=item: (self._switch_mode("room"), self.search_panel.select_item(it)),
                color=pin_color(item.get("camera_id", 0))))
        groups += items
        for serial_entry in load_saved_devices():
            groups.append(PaletteEntry(
                "Devices", serial_entry.get("nickname", "Device"), f"{serial_entry.get('serial', '')} · saved",
                "smartphone", lambda s=serial_entry.get("serial"): self._on_connect_saved_device(s)))
        light = self.palette.get("is_light", False)
        for title, icon, run in (
            ("Scan this PC", "scan-line", lambda: self._switch_mode("file")),
            ("Set up a room", "pencil-ruler", lambda: self._switch_mode("room_setup")),
            ("Manage cameras", "cctv", lambda: self._switch_mode("cameras")),
            ("Connect a phone", "smartphone", lambda: self._switch_mode("device")),
            ("Switch to dark mode" if light else "Switch to light mode",
             "moon" if light else "sun", self._toggle_light_dark),
            ("Open settings", "settings", lambda: self._switch_mode("settings")),
        ):
            groups.append(PaletteEntry("Actions", title, "", icon, run))
        self.palette_dialog.open_with(groups)

    def _toggle_light_dark(self):
        light, accent = theme_parts(self.app_settings.theme)
        new = theme_name(not light, accent)
        self.app_settings.theme = new
        save_app_settings(self.app_settings)
        self.palette = get_palette(new)
        self._apply_theme()
        self.settings_panel.app_settings.theme = new
        self.settings_panel.sync_appearance()

    def _update_mode_status(self):
        mode = self._current_mode
        strip = self.status_strip
        if mode == "room":
            n = len(getattr(self, "_last_active_items", []) or [])
            msg = (f"Tracking {n:,} item{'s' if n != 1 else ''} across {len(self.room_profiles)} "
                   f"room{'s' if len(self.room_profiles) != 1 else ''}")
            last = getattr(self, "_last_detection_at", None)
            if last is not None:
                msg += f" · last detection {int(time.monotonic() - last)}s ago"
            strip.set_status(msg, "success")
        elif mode == "room_setup":
            strip.set_status(f"Editing {self.room_setup_panel._active_profile().name}")
        elif mode == "cameras":
            strip.set_status("Add, discover and configure cameras")
        elif mode == "file":
            strip.set_status(self.file_search_panel.status_summary())
        elif mode == "device":
            strip.set_status(self.device_search_panel.status_summary())
        else:
            strip.set_status("Ready")

    def _get_nav_tab_order(self) -> list:
        raw = self.app_settings.nav_tab_order
        if raw:
            try:
                order = json.loads(raw)
                if sorted(order) == sorted(NAV_TAB_KEYS_DEFAULT):
                    return order
            except (ValueError, TypeError):
                pass
        return list(NAV_TAB_KEYS_DEFAULT)

    def _apply_nav_tab_order(self):
        order = self._get_nav_tab_order()
        buttons = list(self.nav_mode_buttons.values()) + [self.mode_cameras_btn]
        for btn in buttons:
            self.nav_layout.removeWidget(btn)
        i = 0
        for key in order:
            btn = self.nav_mode_buttons.get(key)
            if btn is None:
                continue
            self.nav_layout.insertWidget(self._nav_tabs_insert_index + i, btn)
            i += 1
            # Cameras isn't reorderable on its own - it rides along after Room Setup.
            if key == "room_setup":
                self.nav_layout.insertWidget(self._nav_tabs_insert_index + i, self.mode_cameras_btn)
                i += 1

    def _get_dock_panel_order(self) -> list:
        raw = self.app_settings.dock_panel_order
        if raw:
            try:
                order = json.loads(raw)
                if sorted(order) == sorted(DOCK_PANEL_KEYS_DEFAULT):
                    return order
            except (ValueError, TypeError):
                pass
        return list(DOCK_PANEL_KEYS_DEFAULT)

    def _apply_dock_panel_order(self):
        order = self._get_dock_panel_order()
        docks = {"camera_dock": self.camera_dock, "found_items_dock": self.found_items_dock}
        areas = [Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea]
        for area, key in zip(areas, order):
            dock = docks.get(key)
            if dock is not None:
                # A layout saved while the dock was torn off would otherwise
                # leave it floating with no way to drag it back.
                dock.setFloating(False)
                self.room_widget.addDockWidget(area, dock)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange and hasattr(self, "maximize_btn"):
            self.maximize_btn._icon_name = "copy" if self.isMaximized() else "square"
            self._tint_window_button(self.maximize_btn)
            self.maximize_btn.setToolTip("Restore" if self.isMaximized() else "Maximize")
        super().changeEvent(event)

    def _switch_mode(self, mode):
        self.camera_spotlight.close_spotlight()
        self._current_mode = mode
        self.room_widget.hide()
        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.camera_settings_panel.hide()
        self.settings_panel.hide()
        self.mode_room_btn.setChecked(False)
        self.mode_room_setup_btn.setChecked(False)
        self.mode_file_btn.setChecked(False)
        self.mode_device_btn.setChecked(False)
        self.mode_cameras_btn.setChecked(False)
        self.settings_btn.setChecked(False)

        if mode == "room":
            self.room_widget.show()
            self.mode_room_btn.setChecked(True)
        elif mode == "room_setup":
            self.room_setup_panel.show()
            self.mode_room_setup_btn.setChecked(True)
        elif mode == "file":
            self.file_search_panel.show()
            self.mode_file_btn.setChecked(True)
        elif mode == "device":
            self.device_search_panel.show()
            self.mode_device_btn.setChecked(True)
        elif mode == "cameras":
            self.camera_settings_panel.show()
            self.mode_cameras_btn.setChecked(True)
        elif mode == "settings":
            self.settings_panel.show()
            self.settings_btn.setChecked(True)
        self._update_mode_status()

    # ---------------- Title shortcut: bind "Found It" to any button ----------------

    def _build_shortcut_registry(self):
        """Map every QPushButton reachable from self via attributes (recursing
        into nested panels/tabs) to a dotted path, e.g. "room_setup_panel.scan_room_btn".
        Rebuilt lazily so buttons created after startup (rare) still get picked up."""
        self._shortcut_paths = {}
        self._shortcut_buttons = {}
        self._collect_button_paths(self, "", set(), self._shortcut_paths, self._shortcut_buttons)

    def _collect_button_paths(self, root, prefix, seen, paths, buttons, depth=0):
        if depth > 6 or id(root) in seen:
            return
        seen.add(id(root))
        try:
            items = list(vars(root).items())
        except TypeError:
            return
        for name, value in items:
            if name.startswith("_"):
                continue
            path = f"{prefix}.{name}" if prefix else name
            if isinstance(value, QPushButton):
                paths[path] = value
                buttons[id(value)] = path
            elif isinstance(value, QWidget):
                self._collect_button_paths(value, path, seen, paths, buttons, depth + 1)

    def _shortcut_excluded_buttons(self):
        return {
            self.mode_room_btn, self.mode_room_setup_btn, self.mode_file_btn,
            self.mode_device_btn, self.settings_btn,
            self.minimize_btn, self.maximize_btn, self.close_btn,
        }

    def start_shortcut_binding(self):
        self._build_shortcut_registry()
        self._binding_shortcut = True
        self._switch_mode("room")
        self.statusBar().showMessage(
            "Double-click any button to make it the \"Found It\" shortcut. Tabs still work "
            "normally. Press Esc to cancel."
        )
        QApplication.instance().installEventFilter(self)

    def _stop_shortcut_binding(self):
        self._binding_shortcut = False
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, event):
        if getattr(obj, "_icon_name", None) and obj in (
                getattr(self, "minimize_btn", None), getattr(self, "maximize_btn", None),
                getattr(self, "close_btn", None)):
            if event.type() == QEvent.Enter:
                self._tint_window_button(obj, True)
            elif event.type() == QEvent.Leave:
                self._tint_window_button(obj, False)
        if getattr(self, "_binding_shortcut", False):
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._stop_shortcut_binding()
                self.statusBar().showMessage("Shortcut selection cancelled.", 3000)
                return True
            if event.type() == QEvent.MouseButtonDblClick and isinstance(obj, QPushButton):
                if obj in self._shortcut_excluded_buttons():
                    return False
                path = self._shortcut_buttons.get(id(obj))
                self._stop_shortcut_binding()
                if path is not None:
                    self.app_settings.title_hotkey_action = f"button:{path}"
                    self.app_settings.title_hotkey_label = obj.text() or path.rsplit(".", 1)[-1]
                    save_app_settings(self.app_settings)
                    self._refresh_title_hotkey()
                    self.statusBar().showMessage(
                        f"\"Found It\" now opens: {self.app_settings.title_hotkey_label}", 4000
                    )
                else:
                    self.statusBar().showMessage("That button can't be used as a shortcut.", 4000)
                return True
        return super().eventFilter(obj, event)

    def _refresh_title_hotkey(self):
        action = self.app_settings.title_hotkey_action
        if action.startswith("button:"):
            self.app_title.setCursor(Qt.PointingHandCursor)
            label = self.app_settings.title_hotkey_label or action[len("button:"):]
            self.app_title.setToolTip(f"Shortcut: {label}")
        else:
            self.app_title.setCursor(Qt.ArrowCursor)
            self.app_title.setToolTip("")

    def _on_title_clicked(self):
        action = self.app_settings.title_hotkey_action
        if not action.startswith("button:"):
            return
        path = action[len("button:"):]
        if not hasattr(self, "_shortcut_paths"):
            self._build_shortcut_registry()
        btn = self._shortcut_paths.get(path)
        if btn is None:
            self._build_shortcut_registry()
            btn = self._shortcut_paths.get(path)
        if btn is not None:
            self._reveal_and_click(btn)

    def _reveal_and_click(self, btn: QPushButton):
        # Show whichever nested QTabWidget page(s) the button lives inside.
        for tabs in self.findChildren(QTabWidget):
            if tabs.isAncestorOf(btn):
                for i in range(tabs.count()):
                    if tabs.widget(i) is btn or tabs.widget(i).isAncestorOf(btn):
                        tabs.setCurrentIndex(i)
                        break

        # Show whichever top-level mode panel the button lives inside.
        panels = {
            "room": self.room_widget,
            "room_setup": self.room_setup_panel,
            "file": self.file_search_panel,
            "device": self.device_search_panel,
            "cameras": self.camera_settings_panel,
            "settings": self.settings_panel,
        }
        for mode, panel in panels.items():
            if panel.isAncestorOf(btn):
                self._switch_mode(mode)
                break

        btn.click()

    def _show_room_menu(self):
        menu = QMenu(self)
        for profile in self.room_profiles:
            action = menu.addAction(profile.name)
            action.setCheckable(True)
            action.setChecked(profile.id == self.active_room_id)
            action.triggered.connect(lambda checked, rid=profile.id: self._switch_display_room(rid))
        menu.exec_(self.main_room_btn.mapToGlobal(self.main_room_btn.rect().bottomLeft()))

    def _refresh_room_map_selector(self):
        """Repopulate the room dropdown next to the "Room Map" heading from
        the rooms currently defined in Room Setup, and select whichever one
        is being displayed."""
        self.room_map_selector.blockSignals(True)
        self.room_map_selector.clear()
        for profile in self.room_profiles:
            self.room_map_selector.addItem(profile.name, profile.id)
        index = self.room_map_selector.findData(self.active_room_id)
        if index >= 0:
            self.room_map_selector.setCurrentIndex(index)
        self.room_map_selector.blockSignals(False)

    def _on_room_map_selector_changed(self, index: int):
        room_id = self.room_map_selector.itemData(index)
        if room_id is not None:
            self._switch_display_room(room_id)

    def _switch_display_room(self, room_id: str):
        if room_id == self.active_room_id or self._get_profile(room_id) is None:
            return
        self.active_room_id = room_id
        self.app_settings.active_room_id = room_id
        save_app_settings(self.app_settings)
        self._refresh_display_room_ui()

    def _on_settings_updated(self):
        self.app_settings = load_app_settings()
        # load_app_settings() returns a new object each time, so the
        # detection worker thread (which was handed the old one) needs its
        # reference refreshed too, or it'd keep using stale confidence/
        # frame-skip/dewarp values forever.
        self.detection_worker.app_settings = self.app_settings
        self.detector.set_model(self.app_settings.detection_model)
        self.palette = get_palette(self.app_settings.theme)
        self._apply_theme()
        self.dewarp_check.setChecked(self.app_settings.dewarp_default)
        self._update_detection_caption()
        self._apply_nav_tab_order()
        self._apply_dock_panel_order()
        self._start_all_room_cameras()

    def _on_connect_saved_device(self, serial: str):
        self._switch_mode("device")
        self.device_search_panel.connect_saved_device(serial)

    def _on_room_updated(self):
        # Mutate the existing list in place rather than rebinding
        # self.room_profiles - the detection worker thread holds a direct
        # reference to this same list object so it always sees current
        # rooms without needing to be re-wired every time they change.
        self.room_profiles[:] = load_room_profiles()
        if self._get_profile(self.active_room_id) is None:
            self.active_room_id = self.room_profiles[0].id
            self.app_settings.active_room_id = self.active_room_id
            save_app_settings(self.app_settings)
        self.search_panel.set_room_names({p.id: p.name for p in self.room_profiles})
        self._start_all_room_cameras()
        # Room Setup's own Save writes camera position/removal changes made
        # by dragging on its canvas - keep the Cameras tab's in-memory copy
        # from going stale and clobbering those on its next Save.
        self.camera_settings_panel.reload_profiles()

    def _on_camera_settings_updated(self):
        self._on_settings_updated()
        # The Cameras tab's own Save writes camera add/rename/toggle/remove
        # changes - keep Room Setup's in-memory copy (and its canvas) from
        # going stale and clobbering those on its next Save Room.
        self.room_setup_panel.reload_profiles()

    def _on_rooms_imported(self):
        self._on_room_updated()
        self.room_setup_panel.reload_profiles()

    # ---------------- First-run tutorial / What's New ----------------

    def maybe_show_startup_dialogs(self):
        """Show the first-run walkthrough, or the notes for an update, once
        the window is actually up. Called from main() rather than __init__
        because a modal dialog opened before the window is shown would leave
        the user staring at it with no app behind it."""
        action, releases = pending_startup(self.app_settings)
        if action == "tutorial":
            self.show_tutorial()
        elif action == "whats_new":
            self.show_whats_new(releases)

    def show_whats_new(self, releases=None):
        # No argument means someone asked for the notes from Settings, rather
        # than an update triggering them - show this version's.
        if not releases:
            releases = [current_release()]
        dialog = WhatsNewDialog(self.palette, releases, self)
        dialog.tutorial_requested.connect(self.show_tutorial)
        dialog.center_on(self)
        dialog.exec_()
        self._record_guides_seen()

    def show_tutorial(self):
        # The tour switches tabs as it goes, so put the user back where they
        # were once it's over instead of stranding them on the last step's tab.
        return_mode = self._current_mode
        dialog = TutorialDialog(self.palette, self)
        dialog.mode_requested.connect(self._switch_mode)
        dialog.center_on(self)
        dialog.exec_()
        self._record_guides_seen(tutorial_done=True)
        self._switch_mode(return_mode)

    def _record_guides_seen(self, tutorial_done: bool = False):
        """Written out immediately rather than at shutdown: a crash between
        now and then shouldn't mean the same splash again on every launch."""
        self.app_settings.last_seen_version = APP_VERSION
        if tutorial_done:
            self.app_settings.tutorial_completed = True
        save_app_settings(self.app_settings)

    def _setup_timers(self):
        # Detection (camera capture -> dewarp -> YOLO inference -> merge)
        # runs on its own QThread so a slow inference pass doesn't freeze
        # the UI. Results come back via cycle_done, handled on this
        # (the GUI) thread since DB writes and widget updates must be.
        self.detection_worker = DetectionWorker(self.detector, self.app_settings)
        self.detection_worker.room_profiles = self.room_profiles
        self.detection_worker.room_cameras = self.room_cameras
        self.detection_worker.room_dewarpers = self.room_dewarpers
        self.detection_worker.room_mappers = self.room_mappers
        self.detection_worker.dewarp_enabled = self.dewarp_check.isChecked()
        self.detection_worker.cycle_done.connect(self._on_detection_cycle_done)
        self.dewarp_check.toggled.connect(self._on_dewarp_toggled)

        self._detection_thread = QThread(self)
        self.detection_worker.moveToThread(self._detection_thread)
        self._detection_thread.started.connect(self.detection_worker.start)
        self._detection_thread.start()

        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._display_cycle)
        self._display_timer.start(50)

        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._cleanup_cycle)
        self._cleanup_timer.start(30000)

        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_display)
        self._refresh_timer.start(2000)

    def _start_all_room_cameras(self):
        """(Re)start every saved room profile's cameras so all of them keep
        tracking in the background, regardless of which one is displayed."""
        for cams in self.room_cameras.values():
            for cam in cams.values():
                cam.stop()

        # Clear in place rather than rebinding - the detection worker
        # thread holds direct references to these same dict objects, so
        # replacing them here would leave it watching stale, empty dicts.
        self.room_cameras.clear()
        self.room_dewarpers.clear()
        self.room_mappers.clear()
        used_device_ids = {}

        for profile in self.room_profiles:
            self.room_mappers[profile.id] = ItemMapper(profile)
            cams = {}
            dewarpers = {}

            for cam_cfg in profile.cameras:
                if not cam_cfg.get("enabled"):
                    continue

                cam_id = cam_cfg["id"]
                if cam_id in used_device_ids:
                    self.statusBar().showMessage(
                        f"Camera {cam_id} in \"{profile.name}\" skipped - already in use by "
                        f"\"{used_device_ids[cam_id]}\". Give each room's cameras distinct IDs."
                    )
                    continue

                cam = CameraCapture(cam_id)
                if not cam.start():
                    continue

                used_device_ids[cam_id] = profile.name
                cams[cam_id] = cam

                if cam_cfg.get("is_360"):
                    dewarpers[cam_id] = EquirectangularDewarp(fov=90.0, num_views=4)
                elif cam_cfg.get("is_180") or self.app_settings.dewarp_default:
                    # A 180 deg lens is a fisheye lens - its barrel distortion
                    # is severe enough at the edges that it's always worth
                    # correcting, regardless of the app-wide dewarp default.
                    dewarper = FisheyeDewarp(cam_id)
                    frame = cam.get_frame()
                    if frame is not None:
                        h, w = frame.shape[:2]
                        dewarper.load_calibration((w, h))
                    dewarpers[cam_id] = dewarper

            self.room_cameras[profile.id] = cams
            self.room_dewarpers[profile.id] = dewarpers

        self._refresh_display_room_ui()

    def _refresh_display_room_ui(self):
        """Rebuild the camera tabs and room map for whichever room is
        currently selected as the displayed "Main Room" - the underlying
        camera captures for every room keep running regardless."""
        self.camera_spotlight.close_spotlight()
        self.cam_tabs.clear()
        self.cam_views = {}

        profile = self._get_profile(self.active_room_id)
        if profile is None:
            return

        cams = self.room_cameras.get(profile.id, {})
        for cam_cfg in profile.cameras:
            if not cam_cfg.get("enabled"):
                continue
            cam_id = cam_cfg["id"]
            if cam_id not in cams:
                continue
            label = cam_cfg.get("label", f"Camera {cam_id}")
            view = CameraView(cam_id, palette=self.palette, label=label)
            view.setToolTip("Double-click to enlarge")
            view.expand_requested.connect(self._open_camera_spotlight)
            self.cam_tabs.addTab(view, label)
            self.cam_views[cam_id] = view

        self.room_map.set_room_size(profile.width_m, profile.height_m)
        self.room_map.set_zones(profile.zones)
        self.room_map.set_cameras(profile.cameras)
        self.main_room_btn.setText(profile.name)
        self._refresh_room_map_selector()
        self._rebuild_cam_switcher()
        self._update_detection_caption()

    def _on_dewarp_toggled(self, checked: bool):
        self.detection_worker.dewarp_enabled = checked

    @staticmethod
    def _one_detection_per_label(merged: list) -> list:
        """Collapse a cycle's detections down to the best-scoring one per
        label.

        Only one row per (label, room) can be active at a time - see
        Database.deactivate_other_positions - so two detections of the same
        label reaching the database individually cannot both be stored. What
        happened instead was that each one failed to find the other's row,
        inserted its own, wrote a snapshot, and deactivated its rival, over
        and over at the detection frame rate. Picking a winner here settles
        that in memory rather than letting the two fight on disk.

        The one-instance-per-label limit is the existing data model, not
        something introduced here: telling two objects of the same class
        apart needs real tracking IDs, which the detector doesn't produce.
        """
        best: dict = {}
        for det in merged:
            key = det["label"].lower()
            if key not in best or det["confidence"] > best[key]["confidence"]:
                best[key] = det
        return list(best.values())

    @staticmethod
    def _delete_snapshots(paths) -> None:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                # Already gone, or held open by a viewer - the row's
                # reference to it has been cleared either way.
                pass

    def _on_detection_cycle_done(self, results: list, total_detections: int):
        """Runs on the GUI thread (queued signal from the detection worker
        thread) - this is where DB writes and status text updates happen,
        since sqlite connections and widgets aren't thread-safe to touch
        from the worker."""
        for profile_id, merged, frames_by_cam in results:
            mapper = self.room_mappers.get(profile_id)
            if mapper is None:
                continue

            # Re-anchor this room's camera->room mapping before computing
            # positions this cycle, using whichever detections match
            # furniture already placed on the room map.
            mapper.calibrate_from_items(merged)

            for det in self._one_detection_per_label(merged):
                room_x, room_y = mapper.pixel_to_room(
                    det["zone_x"], det["zone_y"], det["camera_id"]
                )
                zone_name = mapper.get_zone_name(room_x, room_y)

                existing = self.db.find_active_item(det["label"], profile_id)

                if existing:
                    bbox = (det["bbox_x1"], det["bbox_y1"], det["bbox_x2"], det["bbox_y2"])
                    self.db.update_item_position(
                        existing["id"], det["zone_x"], det["zone_y"],
                        det["confidence"], zone_name, bbox=bbox,
                        camera_id=det["camera_id"],
                    )
                    self.db.deactivate_other_positions(det["label"], profile_id, existing["id"])
                else:
                    # Only a genuinely new sighting is worth the disk write. An
                    # already-tracked item takes the update branch above, which
                    # leaves its existing snapshot in place.
                    snapshot_path = None
                    cam_frame = frames_by_cam.get(det["camera_id"])
                    if cam_frame is not None:
                        snapshot_path = self.detector.save_snapshot(
                            cam_frame, det["bbox_y1"], det["bbox_y2"],
                            det["bbox_x1"], det["bbox_x2"], det["label"], det["camera_id"]
                        )
                    if snapshot_path is not None:
                        # Now that a replacement exists, drop the images from
                        # this object's earlier sightings - deleted only after
                        # the new one is safely written, so a failed capture
                        # never leaves the item with no snapshot at all.
                        self._delete_snapshots(
                            self.db.take_previous_snapshots(det["label"], profile_id)
                        )
                    item = DetectedItem(
                        label=det["label"],
                        confidence=det["confidence"],
                        camera_id=det["camera_id"],
                        zone_x=det["zone_x"],
                        zone_y=det["zone_y"],
                        bbox_x1=det["bbox_x1"],
                        bbox_y1=det["bbox_y1"],
                        bbox_x2=det["bbox_x2"],
                        bbox_y2=det["bbox_y2"],
                        snapshot_path=snapshot_path,
                        zone_name=zone_name,
                        room_id=profile_id,
                    )
                    new_id = self.db.insert_item(item)
                    self.db.deactivate_other_positions(det["label"], profile_id, new_id)

        self._last_detection_at = time.monotonic()
        if self._current_mode == "room":
            self._update_mode_status()
        self._update_tracked_highlight()

    def _display_cycle(self):
        cams = self.room_cameras.get(self.active_room_id, {})
        dewarpers = self.room_dewarpers.get(self.active_room_id, {})

        for cam_id, cam in cams.items():
            frame = cam.get_frame()
            if frame is None:
                continue

            if self.dewarp_check.isChecked() and cam_id in dewarpers:
                frame = dewarpers[cam_id].dewarp(frame)

            view = self.cam_views.get(cam_id)
            if view is not None:
                view.update_frame(frame)
            if self.camera_spotlight.camera_id == cam_id:
                self.camera_spotlight.update_frame(frame)

        self._display_camera_settings_previews()

    def _display_camera_settings_previews(self):
        """Feed live frames into the Cameras tab's grid thumbnails / detail
        preview - it tracks its own "which room am I editing" state
        (independent of the displayed room above), so it's kept live here
        rather than folding it into the loop over the active display room."""
        if not self.camera_settings_panel.isVisible():
            return

        panel = self.camera_settings_panel
        cams = self.room_cameras.get(panel.active_profile_id, {})
        dewarpers = self.room_dewarpers.get(panel.active_profile_id, {})

        for cam_id, view in panel.live_views.items():
            cam = cams.get(cam_id)
            if cam is None:
                continue
            frame = cam.get_frame()
            if frame is None:
                continue
            if cam_id in dewarpers:
                frame = dewarpers[cam_id].dewarp(frame)
            view.update_frame(frame)

    def _cleanup_cycle(self):
        self.db.deactivate_old_items(ITEM_INACTIVE_SECONDS)

    def _refresh_display(self):
        active_room_items = self.db.get_active_items(room_id=self.active_room_id)
        mapper = self.room_mappers.get(self.active_room_id)

        map_items = []
        if mapper is not None:
            for item in active_room_items:
                room_x, room_y = mapper.pixel_to_room(
                    item["zone_x"], item["zone_y"], item["camera_id"]
                )
                map_items.append({
                    **item,
                    "room_x": room_x,
                    "room_y": room_y,
                })
        self.room_map.update_items(map_items)

        all_active_items = self.db.get_active_items()
        self.search_panel.show_all_items(all_active_items)
        self._last_active_items = all_active_items
        n_rooms = len(self.room_profiles)
        self.status_indicator.set_text(
            f"Tracking {len(all_active_items):,} item{'s' if len(all_active_items) != 1 else ''} · "
            f"{n_rooms} room{'s' if n_rooms != 1 else ''}")
        if self._current_mode == "room":
            self._update_mode_status()

    def _on_item_selected(self, item: dict):
        room_id = item.get("room_id")
        if room_id is not None:
            self._switch_display_room(room_id)
        self.room_map.set_selected_item(item.get("id"))

        cam_id = item.get("camera_id")
        view = self.cam_views.get(cam_id)
        if view is None:
            return

        tab_index = self.cam_tabs.indexOf(view)
        if tab_index != -1:
            self.cam_tabs.setCurrentIndex(tab_index)

        if self._tracked_view is not None and self._tracked_view is not view:
            self._tracked_view.clear_highlight()

        bbox = (
            item.get("bbox_x1"), item.get("bbox_y1"),
            item.get("bbox_x2"), item.get("bbox_y2"),
        )
        if None not in bbox:
            view.set_highlight(bbox, item.get("label"), persistent=True)
            self._tracked_item_id = item.get("id")
            self._tracked_view = view

    def _update_tracked_highlight(self):
        """Keeps the highlight on a selected item following it live as new
        detection cycles come in - including handing off to a different
        camera's tab if it walks into another camera's view. Once it's no
        longer active (moved out of every camera's view, or picked up),
        stop chasing it but deliberately leave the box drawn at wherever it
        was last seen instead of clearing it."""
        if self._tracked_item_id is None:
            return

        item = self.db.get_item(self._tracked_item_id)
        if item is None or not item.get("is_active") or item.get("room_id") != self.active_room_id:
            self._tracked_item_id = None
            return

        bbox = (item.get("bbox_x1"), item.get("bbox_y1"), item.get("bbox_x2"), item.get("bbox_y2"))
        if None in bbox:
            return

        view = self.cam_views.get(item.get("camera_id"))
        if view is None:
            return

        if view is not self._tracked_view:
            if self._tracked_view is not None:
                self._tracked_view.clear_highlight()
            tab_index = self.cam_tabs.indexOf(view)
            if tab_index != -1:
                self.cam_tabs.setCurrentIndex(tab_index)
            self._tracked_view = view

        view.set_highlight(bbox, item.get("label"), persistent=True)

    def _restore_room_tracker_layout(self, tracker: QMainWindow):
        state_b64 = self.app_settings.room_tracker_layout
        if not state_b64:
            return
        try:
            state = QByteArray.fromBase64(state_b64.encode())
            tracker.restoreState(state)
        except Exception:
            pass

    def _save_room_tracker_layout(self):
        state = self.room_widget.saveState()
        self.app_settings.room_tracker_layout = bytes(state.toBase64()).decode()
        save_app_settings(self.app_settings)

    def closeEvent(self, event):
        self._save_room_tracker_layout()
        self.room_setup_panel.save_layout()
        self._detection_thread.quit()
        self._detection_thread.wait(2000)
        for cams in self.room_cameras.values():
            for cam in cams.values():
                cam.stop()
        self.db.close()
        event.accept()
