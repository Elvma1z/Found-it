import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from found_it.config import DB_PATH, DB_DIR
from found_it.storage.models import DetectedItem


class Database:
    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                camera_id INTEGER NOT NULL,
                zone_x REAL,
                zone_y REAL,
                bbox_x1 INTEGER,
                bbox_y1 INTEGER,
                bbox_x2 INTEGER,
                bbox_y2 INTEGER,
                confidence REAL,
                snapshot_path TEXT,
                zone_name TEXT,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                is_active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS room_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_width_m REAL DEFAULT 4.0,
                room_height_m REAL DEFAULT 4.0,
                camera0_corner TEXT DEFAULT 'top-left',
                camera1_corner TEXT DEFAULT 'bottom-right',
                zones TEXT DEFAULT '[]'
            );
        """)

        cursor = self.conn.execute("PRAGMA table_info(room_config)")
        columns = {row[1] for row in cursor.fetchall()}
        if "center_camera_enabled" not in columns:
            self.conn.execute(
                "ALTER TABLE room_config ADD COLUMN center_camera_enabled INTEGER DEFAULT 0"
            )
        if "center_camera_position" not in columns:
            self.conn.execute(
                "ALTER TABLE room_config ADD COLUMN center_camera_position TEXT DEFAULT 'center'"
            )

        item_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(items)").fetchall()}
        if "zone_name" not in item_columns:
            self.conn.execute("ALTER TABLE items ADD COLUMN zone_name TEXT")
        if "room_id" not in item_columns:
            self.conn.execute("ALTER TABLE items ADD COLUMN room_id TEXT DEFAULT 'main'")

        self.conn.commit()

    def insert_item(self, item: DetectedItem) -> int:
        cursor = self.conn.execute(
            """INSERT INTO items
               (label, camera_id, zone_x, zone_y, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                confidence, snapshot_path, zone_name, room_id, first_seen, last_seen, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.label, item.camera_id, item.zone_x, item.zone_y,
             item.bbox_x1, item.bbox_y1, item.bbox_x2, item.bbox_y2,
             item.confidence, item.snapshot_path, item.zone_name, item.room_id,
             item.first_seen.isoformat(), item.last_seen.isoformat(),
             int(item.is_active))
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_item_position(self, item_id: int, zone_x: float, zone_y: float,
                             confidence: float, zone_name: Optional[str] = None,
                             bbox: Optional[tuple] = None):
        # bbox is refreshed here too (not just on insert) so a highlight
        # drawn from the item's current DB row reflects where it actually
        # is now instead of freezing at wherever it was first detected.
        if bbox is not None:
            self.conn.execute(
                """UPDATE items SET zone_x = ?, zone_y = ?, confidence = ?,
                   zone_name = ?, bbox_x1 = ?, bbox_y1 = ?, bbox_x2 = ?, bbox_y2 = ?,
                   last_seen = ?, is_active = 1
                   WHERE id = ?""",
                (zone_x, zone_y, confidence, zone_name, *bbox,
                 datetime.now().isoformat(), item_id)
            )
        else:
            self.conn.execute(
                """UPDATE items SET zone_x = ?, zone_y = ?, confidence = ?,
                   zone_name = ?, last_seen = ?, is_active = 1
                   WHERE id = ?""",
                (zone_x, zone_y, confidence, zone_name, datetime.now().isoformat(), item_id)
            )
        self.conn.commit()

    def get_item(self, item_id: int) -> Optional[dict]:
        cursor = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def rename_item(self, item_id: int, new_label: str):
        self.conn.execute(
            "UPDATE items SET label = ? WHERE id = ?",
            (new_label, item_id)
        )
        self.conn.commit()

    def deactivate_old_items(self, seconds: int):
        cutoff = datetime.now().timestamp() - seconds
        self.conn.execute(
            """UPDATE items SET is_active = 0
               WHERE is_active = 1 AND last_seen < ?""",
            (datetime.fromtimestamp(cutoff).isoformat(),)
        )
        self.conn.commit()

    def find_items(self, label: str) -> list[dict]:
        cursor = self.conn.execute(
            """SELECT * FROM items
               WHERE LOWER(label) LIKE LOWER(?)
               ORDER BY last_seen DESC""",
            (f"%{label}%",)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_active_items(self, room_id: Optional[str] = None) -> list[dict]:
        if room_id is not None:
            cursor = self.conn.execute(
                """SELECT * FROM items WHERE is_active = 1 AND room_id = ? ORDER BY last_seen DESC""",
                (room_id,)
            )
        else:
            cursor = self.conn.execute(
                """SELECT * FROM items WHERE is_active = 1 ORDER BY last_seen DESC"""
            )
        return [dict(row) for row in cursor.fetchall()]

    def count_items(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM items")
        return cursor.fetchone()[0]

    def clear_all_items(self):
        self.conn.execute("DELETE FROM items")
        self.conn.commit()

    def get_recent_items(self, limit: int = 50, room_id: Optional[str] = None) -> list[dict]:
        if room_id is not None:
            cursor = self.conn.execute(
                """SELECT * FROM items WHERE room_id = ? ORDER BY last_seen DESC LIMIT ?""",
                (room_id, limit)
            )
        else:
            cursor = self.conn.execute(
                """SELECT * FROM items ORDER BY last_seen DESC LIMIT ?""",
                (limit,)
            )
        return [dict(row) for row in cursor.fetchall()]

    def find_matching_item(self, label: str, camera_id: int,
                           zone_x: float, zone_y: float, room_id: str,
                           tolerance: float = 0.15) -> Optional[dict]:
        cursor = self.conn.execute(
            """SELECT * FROM items
               WHERE LOWER(label) = LOWER(?)
                 AND camera_id = ?
                 AND room_id = ?
                 AND ABS(zone_x - ?) < ?
                 AND ABS(zone_y - ?) < ?
                 AND is_active = 1
               LIMIT 1""",
            (label, camera_id, room_id, zone_x, tolerance, zone_y, tolerance)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_room_config(self, width: float, height: float,
                         cam0_corner: str, cam1_corner: str,
                         zones: list, center_camera_enabled: bool = False,
                         center_camera_position: str = "center"):
        self.conn.execute("DELETE FROM room_config")
        self.conn.execute(
            """INSERT INTO room_config
               (room_width_m, room_height_m, camera0_corner, camera1_corner,
                center_camera_enabled, center_camera_position, zones)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (width, height, cam0_corner, cam1_corner,
             int(center_camera_enabled), center_camera_position, json.dumps(zones))
        )
        self.conn.commit()

    def load_room_config(self) -> dict:
        cursor = self.conn.execute("SELECT * FROM room_config LIMIT 1")
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["zones"] = json.loads(d["zones"])
            return d
        return None

    def close(self):
        self.conn.close()
