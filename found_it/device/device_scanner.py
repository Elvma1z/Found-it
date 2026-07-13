import os
import threading
import tempfile
import time
from typing import List, Optional, Callable
from dataclasses import dataclass

from found_it.device.adb_handler import ADBHandler, DeviceFile
from found_it.fileindex.store import EmbeddingStore, FileEmbedding
from found_it.fileindex.extractor import get_file_description

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".log", ".html", ".htm", ".ini", ".cfg", ".conf"
}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go",
    ".rs", ".rb", ".php", ".sql", ".sh"
}


@dataclass
class DeviceSearchResult:
    path: str
    name: str
    score: float
    file_type: str
    text_preview: str
    size_bytes: int


class DeviceScanner:
    def __init__(self):
        self.adb = ADBHandler()
        self.store = EmbeddingStore()
        self._scanning = False
        self._progress_cb: Optional[Callable] = None
        self._done_cb: Optional[Callable] = None
        self._temp_dir: Optional[str] = None

    def is_adb_available(self) -> bool:
        return self.adb.is_available()

    def connect(self) -> bool:
        return self.adb.connect_device()

    def get_device_name(self) -> str:
        return self.adb.get_device_model()

    def is_connected(self) -> bool:
        return self.adb.connected_device is not None

    def disconnect(self):
        self.adb.disconnect()
        self.store.clear()

    def start_scan(self, paths: Optional[List[str]] = None,
                   progress_callback: Optional[Callable] = None,
                   done_callback: Optional[Callable] = None):
        if self._scanning:
            return
        if not self.is_connected():
            return

        self._progress_cb = progress_callback
        self._done_cb = done_callback
        self._scanning = True

        thread = threading.Thread(
            target=self._scan_worker, args=(paths,), daemon=True
        )
        thread.start()

    def _scan_worker(self, paths: Optional[List[str]]):
        if self._progress_cb:
            self._progress_cb("Scanning device files...")

        files = self.adb.scan_storage(paths, progress_callback=self._progress_cb)

        if self._progress_cb:
            self._progress_cb(f"Found {len(files)} files. Indexing...")

        self._temp_dir = tempfile.mkdtemp(prefix="foundit_device_")

        indexed = 0
        for f in files:
            if not self._is_indexable(f):
                continue

            if self._progress_cb and indexed % 5 == 0:
                self._progress_cb(f"Indexing {indexed}... {f.name}")

            embedding = self._embed_file(f)
            if embedding is not None:
                self.store.add(FileEmbedding(
                    path=f.path,
                    name=f.name,
                    embedding=embedding,
                    file_type=self._get_type(f),
                    text_preview="",
                    size_bytes=f.size_bytes,
                ))
                indexed += 1

        self._cleanup_temp()
        self._scanning = False

        if self._done_cb:
            self._done_cb(indexed)

    def _is_indexable(self, f: DeviceFile) -> bool:
        ext = f.extension.lower()
        return ext in IMAGE_EXTENSIONS or ext in TEXT_EXTENSIONS or ext in CODE_EXTENSIONS

    def _get_type(self, f: DeviceFile) -> str:
        ext = f.extension.lower()
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in CODE_EXTENSIONS:
            return "code"
        return "text"

    def _embed_file(self, f: DeviceFile) -> Optional:
        ext = f.extension.lower()

        if ext in IMAGE_EXTENSIONS:
            return self._embed_device_image(f)
        elif ext in TEXT_EXTENSIONS or ext in CODE_EXTENSIONS:
            return self._embed_device_text(f)
        return None

    def _embed_device_image(self, f: DeviceFile) -> Optional:
        if not self._temp_dir:
            return None

        local = self.adb.pull_file(f.path, self._temp_dir)
        if not local:
            return None

        try:
            embedding = self.store.embed_image(local)
            return embedding
        finally:
            try:
                os.remove(local)
            except OSError:
                pass

    def _embed_device_text(self, f: DeviceFile) -> Optional:
        text = self.adb.read_file_text(f.path, max_bytes=5000)
        if not text.strip():
            return None

        combined = f"{f.name} {text[:300]}"
        return self.store.embed_text(combined)

    def _cleanup_temp(self):
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                import shutil
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
            self._temp_dir = None

    def search(self, query: str, top_k: int = 20) -> List[DeviceSearchResult]:
        if not query.strip() or len(self.store) == 0:
            return []

        query_embedding = self.store.embed_query(query)
        if query_embedding is None:
            return []

        results = self.store.search(query_embedding, top_k=top_k)

        return [
            DeviceSearchResult(
                path=emb.path,
                name=emb.name,
                score=score,
                file_type=emb.file_type,
                text_preview=emb.text_preview,
                size_bytes=emb.size_bytes,
            )
            for emb, score in results
        ]

    def is_scanning(self) -> bool:
        return self._scanning

    def file_count(self) -> int:
        return len(self.store)
