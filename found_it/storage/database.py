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

        # room_id only exists after the ALTER above, so these can't live in
        # the CREATE TABLE script. find_active_item() runs once per detected
        # object per cycle, several times a second, against a table that
        # accumulates history rows - without an index that's a full scan
        # every time.
        # Indexed on LOWER(label), not label: every lookup here compares
        # case-insensitively, and SQLite can't use a plain column index when
        # the query wraps that column in a function.
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_items_room_label
                ON items (room_id, LOWER(label), is_active);
            CREATE INDEX IF NOT EXISTS idx_items_active_seen
                ON items (is_active, last_seen);
        """)

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
                             bbox: Optional[tuple] = None,
                             camera_id: Optional[int] = None,
                             snapshot_path: Optional[str] = None):
        # bbox is refreshed here too (not just on insert) so a highlight
        # drawn from the item's current DB row reflects where it actually
        # is now instead of freezing at wherever it was first detected.
        sets = ["zone_x = ?", "zone_y = ?", "confidence = ?", "zone_name = ?",
                "last_seen = ?"]
        values = [zone_x, zone_y, confidence, zone_name, datetime.now().isoformat()]

        if bbox is not None:
            sets += ["bbox_x1 = ?", "bbox_y1 = ?", "bbox_x2 = ?", "bbox_y2 = ?"]
            values += list(bbox)

        # Which camera has the best view of an object changes from cycle to
        # cycle, so the row follows the camera that currently sees it rather
        # than staying pinned to whichever one happened to see it first.
        if camera_id is not None:
            sets.append("camera_id = ?")
            values.append(camera_id)

        # COALESCE so this only ever fills a blank: an item's snapshot is its
        # "what does this look like" thumbnail and should stay the one taken
        # when it was found, not be rewritten on every re-detection.
        if snapshot_path is not None:
            sets.append("snapshot_path = COALESCE(snapshot_path, ?)")
            values.append(snapshot_path)

        values.append(item_id)
        self.conn.execute(
            f"UPDATE items SET {', '.join(sets)}, is_active = 1 WHERE id = ?",
            values
        )
        self.conn.commit()

    def get_item(self, item_id: int) -> Optional[dict]:
        cursor = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def deactivate_other_positions(self, label: str, room_id: str, keep_item_id: Optional[int] = None):
        """The object was just seen somewhere new, so any other active row for
        this label in the room is a stale past location - deactivate it
        (kept in storage for history) instead of leaving it shown as current
        alongside the new sighting."""
        if keep_item_id is None:
            cursor = self.conn.execute(
                """UPDATE items SET is_active = 0
                   WHERE is_active = 1 AND room_id = ? AND LOWER(label) = LOWER(?)""",
                (room_id, label)
            )
        else:
            cursor = self.conn.execute(
                """UPDATE items SET is_active = 0
                   WHERE is_active = 1 AND room_id = ? AND LOWER(label) = LOWER(?) AND id != ?""",
                (room_id, label, keep_item_id)
            )
        # In the steady state there is nothing to deactivate - the tracked
        # item is already the only active row for its identity. Skipping the
        # commit avoids a disk flush per detection per cycle just to write
        # nothing.
        if cursor.rowcount:
            self.conn.commit()

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
        """Only the current (active) location of a matching item - past
        locations stay in storage but aren't surfaced as search results."""
        cursor = self.conn.execute(
            """SELECT * FROM items
               WHERE LOWER(label) LIKE LOWER(?) AND is_active = 1
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

    def clear_all_items(self) -> list[str]:
        """Drop every detection row, returning the snapshot images those rows
        referenced so the caller can delete them too - otherwise clearing the
        history leaves every JPG on disk with nothing left pointing at it."""
        paths = [row[0] for row in self.conn.execute(
            "SELECT DISTINCT snapshot_path FROM items WHERE snapshot_path IS NOT NULL"
        )]
        self.conn.execute("DELETE FROM items")
        self.conn.commit()
        return paths

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

    def find_active_item(self, label: str, room_id: str) -> Optional[dict]:
        """The row that currently represents this object in this room.

        Identity is (label, room_id) and deliberately nothing else. It used
        to also require the same camera_id and a detection within 0.15 of
        the stored *frame* position, which meant an object that moved across
        the frame, or was picked up by a different camera, read as brand new.
        Combined with deactivate_other_positions() - which allows only one
        active row per (label, room_id) - that turned every re-detection into
        an insert, and every insert wrote another snapshot to disk: two
        detections of one label thrashed against each other several times a
        second, indefinitely.

        Position is an attribute of the item, not part of its identity; a
        moved object is the same object somewhere new.
        """
        cursor = self.conn.execute(
            """SELECT * FROM items
               WHERE LOWER(label) = LOWER(?)
                 AND room_id = ?
                 AND is_active = 1
               ORDER BY last_seen DESC
               LIMIT 1""",
            (label, room_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def take_previous_snapshots(self, label: str, room_id: str) -> list[str]:
        """Detach and hand back every snapshot image belonging to earlier
        sightings of this object, so a freshly written one replaces them
        instead of adding to a pile that grows without bound. The history
        rows themselves stay - only their superseded image reference is
        cleared, which keeps at most one snapshot file per (label, room)."""
        paths = [row[0] for row in self.conn.execute(
            """SELECT DISTINCT snapshot_path FROM items
               WHERE room_id = ? AND LOWER(label) = LOWER(?)
                 AND snapshot_path IS NOT NULL""",
            (room_id, label)
        )]
        if paths:
            self.conn.execute(
                """UPDATE items SET snapshot_path = NULL
                   WHERE room_id = ? AND LOWER(label) = LOWER(?)""",
                (room_id, label)
            )
            self.conn.commit()
        return paths

    def clear_snapshot_references(self):
        """Forget every stored snapshot path, for when the images themselves
        have been deleted out from under the rows."""
        self.conn.execute("UPDATE items SET snapshot_path = NULL WHERE snapshot_path IS NOT NULL")
        self.conn.commit()

    def get_referenced_snapshots(self) -> set:
        """Every snapshot path still pointed at by a row, so callers can tell
        which files on disk are orphans."""
        return {row[0] for row in self.conn.execute(
            "SELECT DISTINCT snapshot_path FROM items WHERE snapshot_path IS NOT NULL"
        )}

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
