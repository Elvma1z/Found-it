import sqlite3
from typing import Optional, List, Dict, Tuple

import numpy as np

from found_it.config import INDEX_DB_PATH, DB_DIR


def _to_blob(arr: np.ndarray) -> bytes:
    return np.asarray(arr, dtype=np.float64).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


class IndexDatabase:
    """Persists the file-search index (embeddings, faces, and named people)
    to disk so a rescan doesn't have to re-embed every file and re-detect
    every face from scratch, and so named people survive a restart."""

    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(INDEX_DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                name TEXT,
                file_type TEXT,
                text_preview TEXT,
                size_bytes INTEGER,
                modified_time REAL,
                embedding BLOB
            );

            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                thumbnail_path TEXT,
                centroid BLOB,
                face_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
                encoding BLOB NOT NULL,
                bbox_top INTEGER, bbox_right INTEGER, bbox_bottom INTEGER, bbox_left INTEGER,
                thumbnail_path TEXT
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self.conn.commit()

    # -- meta -----------------------------------------------------------

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        self.conn.commit()

    # -- files --------------------------------------------------------

    def upsert_file(self, path: str, name: str, file_type: str, text_preview: str,
                    size_bytes: int, modified_time: float, embedding: np.ndarray) -> int:
        self.conn.execute(
            """INSERT INTO files (path, name, file_type, text_preview, size_bytes, modified_time, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   name=excluded.name, file_type=excluded.file_type,
                   text_preview=excluded.text_preview, size_bytes=excluded.size_bytes,
                   modified_time=excluded.modified_time, embedding=excluded.embedding""",
            (path, name, file_type, text_preview, size_bytes, modified_time, _to_blob(embedding))
        )
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
        return row["id"]

    def file_up_to_date(self, path: str, size_bytes: int, modified_time: float) -> bool:
        """Whether path is already indexed with this exact size/mtime and
        still has an embedding, so a rescan can skip re-embedding and
        re-detecting faces for it. A NULL embedding (see
        null_image_embeddings) means it's due for re-embedding even though
        the file itself hasn't changed - e.g. after switching CLIP models."""
        row = self.conn.execute(
            "SELECT size_bytes, modified_time, embedding FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row is None or row["embedding"] is None:
            return False
        return (row["size_bytes"] == size_bytes
                and abs((row["modified_time"] or 0) - modified_time) < 1e-6)

    def null_image_embeddings(self):
        """Force every image's embedding to be recomputed on the next scan
        (e.g. after switching CLIP models) without losing the file's row -
        and therefore without losing the faces/people linked to it, since
        face detection doesn't depend on the CLIP model at all. Text/code
        embeddings (from a separate, unaffected text model) are left alone."""
        self.conn.execute("UPDATE files SET embedding = NULL WHERE file_type = 'image'")
        self.conn.commit()

    def load_all_file_embeddings(self) -> List[Dict]:
        faces_by_file: Dict[int, list] = {}
        for face_row in self.conn.execute("SELECT file_id, encoding FROM faces"):
            faces_by_file.setdefault(face_row["file_id"], []).append(_from_blob(face_row["encoding"]))

        result = []
        for row in self.conn.execute("SELECT * FROM files"):
            if row["embedding"] is None:
                continue
            result.append({
                "id": row["id"],
                "path": row["path"],
                "name": row["name"],
                "file_type": row["file_type"],
                "text_preview": row["text_preview"] or "",
                "size_bytes": row["size_bytes"] or 0,
                "modified_time": row["modified_time"] or 0,
                "embedding": _from_blob(row["embedding"]),
                "face_encodings": faces_by_file.get(row["id"], []),
            })
        return result

    # -- faces / people -------------------------------------------------

    def delete_faces_for_file(self, file_id: int):
        """Clear stale face rows before re-processing a file whose content
        changed (mtime differs from what's stored), so re-detection doesn't
        pile up duplicate faces alongside the old ones."""
        self.conn.execute("DELETE FROM faces WHERE file_id = ?", (file_id,))
        self.conn.commit()

    def add_face(self, file_id: int, person_id: int, encoding: np.ndarray,
                bbox: Tuple[int, int, int, int], thumbnail_path) -> int:
        top, right, bottom, left = bbox
        cursor = self.conn.execute(
            """INSERT INTO faces
               (file_id, person_id, encoding, bbox_top, bbox_right, bbox_bottom, bbox_left, thumbnail_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, person_id, _to_blob(encoding), top, right, bottom, left,
             str(thumbnail_path) if thumbnail_path else None)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_person_centroids(self) -> Dict[int, Tuple[np.ndarray, int]]:
        result = {}
        for row in self.conn.execute("SELECT id, centroid, face_count FROM people"):
            if row["centroid"] is not None:
                result[row["id"]] = (_from_blob(row["centroid"]), row["face_count"] or 0)
        return result

    def create_person(self) -> int:
        cursor = self.conn.execute("INSERT INTO people (name, face_count) VALUES (NULL, 0)")
        self.conn.commit()
        return cursor.lastrowid

    def update_person_centroid(self, person_id: int, centroid: np.ndarray, face_count: int):
        self.conn.execute(
            "UPDATE people SET centroid = ?, face_count = ? WHERE id = ?",
            (_to_blob(centroid), face_count, person_id)
        )
        self.conn.commit()

    def set_person_thumbnail(self, person_id: int, thumbnail_path):
        """Only fills in a blank thumbnail, so the person's gallery avatar
        stays their first-ever detected face rather than churning as more
        of their photos get indexed."""
        self.conn.execute(
            "UPDATE people SET thumbnail_path = ? WHERE id = ? AND thumbnail_path IS NULL",
            (str(thumbnail_path), person_id)
        )
        self.conn.commit()

    def rename_person(self, person_id: int, name: str):
        self.conn.execute(
            "UPDATE people SET name = ? WHERE id = ?",
            (name.strip() or None, person_id)
        )
        self.conn.commit()

    def get_face_thumbnails_for_person(self, person_id: int) -> List[str]:
        rows = self.conn.execute(
            "SELECT thumbnail_path FROM faces WHERE person_id = ? AND thumbnail_path IS NOT NULL",
            (person_id,)
        ).fetchall()
        return [row["thumbnail_path"] for row in rows]

    def delete_person(self, person_id: int):
        """Remove a person and every face linked to them. The photos
        themselves stay indexed and searchable - only the "this is person
        X" tag goes away, so a rescan could cluster those faces into a
        new person later."""
        self.conn.execute("DELETE FROM faces WHERE person_id = ?", (person_id,))
        self.conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
        self.conn.commit()

    def get_people(self) -> List[Dict]:
        """Every person with at least one linked photo, most-photographed
        first. face_count here is the number of *distinct photos* they
        appear in - not the raw clustering counter on the people table,
        which only ever grows (even when a photo is re-processed and
        re-linked) and would otherwise drift from what's actually shown."""
        rows = self.conn.execute(
            """SELECT p.id AS id, p.name AS name, p.thumbnail_path AS thumbnail_path,
                      COUNT(DISTINCT f.file_id) AS face_count
               FROM people p
               JOIN faces f ON f.person_id = p.id
               GROUP BY p.id
               ORDER BY face_count DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_named_people(self) -> List[Tuple[str, np.ndarray]]:
        rows = self.conn.execute(
            "SELECT name, centroid FROM people WHERE name IS NOT NULL AND centroid IS NOT NULL"
        ).fetchall()
        return [(row["name"], _from_blob(row["centroid"])) for row in rows]

    def get_person_id_by_name(self, name: str) -> Optional[int]:
        row = self.conn.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
        return row["id"] if row else None

    def get_files_for_person(self, person_id: int) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT DISTINCT f.* FROM files f
               JOIN faces fc ON fc.file_id = f.id
               WHERE fc.person_id = ?
               ORDER BY f.modified_time DESC""",
            (person_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self.conn.close()
