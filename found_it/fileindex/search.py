import threading
from typing import List, Optional, Callable
from dataclasses import dataclass

from found_it.fileindex.indexer import FileIndexer, FileEntry
from found_it.fileindex.store import EmbeddingStore, FileEmbedding
from found_it.fileindex.extractor import extract_text_preview, get_file_description


@dataclass
class SearchResult:
    path: str
    name: str
    score: float
    file_type: str
    text_preview: str
    size_bytes: int


class FileSearchEngine:
    def __init__(self):
        self.indexer = FileIndexer()
        self.store = EmbeddingStore()
        self._indexing = False
        self._progress_cb: Optional[Callable] = None
        self._done_cb: Optional[Callable] = None

    def start_indexing(self, root_dirs: List[str],
                       progress_callback: Optional[Callable] = None,
                       done_callback: Optional[Callable] = None):
        if self._indexing:
            return

        self._progress_cb = progress_callback
        self._done_cb = done_callback
        self._indexing = True

        def on_scan_done(total_files):
            threading.Thread(
                target=self._embed_worker, daemon=True
            ).start()

        self.indexer.start_scan(
            root_dirs,
            progress_callback=self._on_scan_progress,
            done_callback=on_scan_done
        )

    def _on_scan_progress(self, count, filename):
        if self._progress_cb:
            self._progress_cb(f"Scanning: {count} files found... ({filename})")

    def _embed_worker(self):
        unindexed = self.indexer.get_unindexed()
        total = len(unindexed)

        for i, entry in enumerate(unindexed):
            if self._progress_cb:
                self._progress_cb(
                    f"Indexing {i + 1}/{total}: {entry.name}"
                )

            embedding = None
            text_preview = ""

            if entry.is_image:
                embedding = self.store.embed_image(entry.path)
                text_preview = get_file_description(entry)
            elif entry.is_text or entry.is_code:
                text_preview = extract_text_preview(entry.path)
                if text_preview:
                    combined = f"{entry.name} {text_preview[:200]}"
                    embedding = self.store.embed_text(combined)
                else:
                    embedding = self.store.embed_text(get_file_description(entry))

            if embedding is not None:
                file_emb = FileEmbedding(
                    path=entry.path,
                    name=entry.name,
                    embedding=embedding,
                    file_type="image" if entry.is_image else "text" if entry.is_text else "code",
                    text_preview=text_preview[:300],
                    size_bytes=entry.size_bytes,
                    modified_time=entry.modified_time,
                )
                self.store.add(file_emb)

            self.indexer.mark_indexed(entry.path)

        self._indexing = False
        if self._done_cb:
            self._done_cb(len(self.store))

    def search(self, query: str, top_k: int = 20) -> List[SearchResult]:
        if not query.strip():
            return []

        query_embedding = self.store.embed_query(query)
        if query_embedding is None:
            return []

        results = self.store.search(query_embedding, top_k=top_k)

        search_results = []
        for file_emb, score in results:
            search_results.append(SearchResult(
                path=file_emb.path,
                name=file_emb.name,
                score=score,
                file_type=file_emb.file_type,
                text_preview=file_emb.text_preview,
                size_bytes=file_emb.size_bytes,
            ))

        return search_results

    def is_indexing(self) -> bool:
        return self._indexing or self.indexer.is_scanning()

    def get_stats(self) -> dict:
        stats = self.indexer.get_stats()
        stats["embedded"] = len(self.store)
        return stats

    def get_all_indexed_paths(self) -> set:
        return {e.path for e in self.store.embeddings}
