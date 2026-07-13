import os
import time
import threading
from pathlib import Path
from typing import List, Callable, Optional
from dataclasses import dataclass, field

from found_it.config import DATA_DIR


INDEX_DB = DATA_DIR / "file_index.db"


@dataclass
class FileEntry:
    path: str
    name: str
    extension: str
    size_bytes: int
    modified_time: float
    is_image: bool = False
    is_text: bool = False
    is_code: bool = False
    indexed: bool = False


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".xml", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".html", ".htm"
}

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".scala", ".r", ".m", ".mm", ".sql", ".sh", ".bat", ".ps1",
    ".css", ".scss", ".less", ".vue", ".svelte"
}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".vscode", "dist", "build", ".next", ".cache",
    "AppData", "Program Files", "Program Files (x86)",
    "Windows", "ProgramData"
}


class FileIndexer:
    def __init__(self):
        self.entries: List[FileEntry] = []
        self._lock = threading.Lock()
        self._scanning = False
        self._progress_callback: Optional[Callable] = None
        self._done_callback: Optional[Callable] = None

    def start_scan(self, root_dirs: List[str],
                   progress_callback: Optional[Callable] = None,
                   done_callback: Optional[Callable] = None):
        if self._scanning:
            return

        self._progress_callback = progress_callback
        self._done_callback = done_callback
        self._scanning = True

        thread = threading.Thread(
            target=self._scan_worker, args=(root_dirs,), daemon=True
        )
        thread.start()

    def _scan_worker(self, root_dirs: List[str]):
        new_entries = []
        count = 0

        for root_dir in root_dirs:
            root = Path(root_dir)
            if not root.exists():
                continue

            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames
                    if d not in SKIP_DIRS and not d.startswith(".")
                ]

                for filename in filenames:
                    filepath = Path(dirpath) / filename
                    ext = filepath.suffix.lower()

                    is_image = ext in IMAGE_EXTENSIONS
                    is_text = ext in TEXT_EXTENSIONS
                    is_code = ext in CODE_EXTENSIONS

                    if not (is_image or is_text or is_code):
                        continue

                    try:
                        stat = filepath.stat()
                        entry = FileEntry(
                            path=str(filepath.resolve()),
                            name=filename,
                            extension=ext,
                            size_bytes=stat.st_size,
                            modified_time=stat.st_mtime,
                            is_image=is_image,
                            is_text=is_text,
                            is_code=is_code,
                        )
                        new_entries.append(entry)
                        count += 1

                        if count % 100 == 0 and self._progress_callback:
                            self._progress_callback(count, filename)

                    except (OSError, PermissionError):
                        continue

        with self._lock:
            existing_paths = {e.path for e in self.entries}
            for entry in new_entries:
                if entry.path not in existing_paths:
                    self.entries.append(entry)

        self._scanning = False
        if self._done_callback:
            self._done_callback(len(self.entries))

    def get_unindexed(self) -> List[FileEntry]:
        with self._lock:
            return [e for e in self.entries if not e.indexed]

    def mark_indexed(self, path: str):
        with self._lock:
            for entry in self.entries:
                if entry.path == path:
                    entry.indexed = True
                    break

    def is_scanning(self) -> bool:
        return self._scanning

    def get_stats(self) -> dict:
        with self._lock:
            total = len(self.entries)
            images = sum(1 for e in self.entries if e.is_image)
            texts = sum(1 for e in self.entries if e.is_text)
            codes = sum(1 for e in self.entries if e.is_code)
            indexed = sum(1 for e in self.entries if e.indexed)
            return {
                "total": total,
                "images": images,
                "texts": texts,
                "codes": codes,
                "indexed": indexed,
            }
