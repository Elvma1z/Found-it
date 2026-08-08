import os
import re
import hashlib
import threading
from typing import List, Optional, Callable, Tuple
from dataclasses import dataclass

from found_it.fileindex.indexer import FileIndexer, FileEntry
from found_it.fileindex.store import EmbeddingStore, FileEmbedding
from found_it.fileindex.extractor import extract_text_preview, get_file_description
from found_it.fileindex.faces import get_face_encodings, best_face_match_distance, SAME_PERSON_DISTANCE
from found_it.fileindex.phash import get_perceptual_hash, NEAR_DUPLICATE_HASH_DISTANCE


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
        self._cancel_requested = False
        self._progress_cb: Optional[Callable] = None
        self._done_cb: Optional[Callable] = None
        self._hash_cache: dict = {}
        self._phash_cache: dict = {}

    def start_indexing(self, root_dirs: List[str],
                       progress_callback: Optional[Callable] = None,
                       done_callback: Optional[Callable] = None):
        if self._indexing:
            return

        self._progress_cb = progress_callback
        self._done_cb = done_callback
        self._indexing = True
        self._cancel_requested = False

        def on_scan_done(total_files):
            if self._cancel_requested:
                self._indexing = False
                if self._done_cb:
                    self._done_cb(len(self.store))
                return
            threading.Thread(
                target=self._embed_worker, daemon=True
            ).start()

        self.indexer.start_scan(
            root_dirs,
            progress_callback=self._on_scan_progress,
            done_callback=on_scan_done
        )

    def cancel(self):
        """Stop an in-progress scan or indexing pass as soon as possible - files
        already embedded stay searchable, whatever hadn't been reached yet is
        just skipped rather than left half-done."""
        self._cancel_requested = True
        self.indexer.cancel_scan()

    def _on_scan_progress(self, count, filename):
        if self._progress_cb:
            self._progress_cb(f"Scanning: {count} files found... ({filename})")

    def _embed_worker(self):
        unindexed = self.indexer.get_unindexed()
        total = len(unindexed)

        for i, entry in enumerate(unindexed):
            if self._cancel_requested:
                break
            if self._progress_cb:
                self._progress_cb(
                    f"Indexing {i + 1}/{total}: {entry.name}"
                )

            embedding = None
            text_preview = ""
            face_encodings = []

            if entry.is_image:
                embedding = self.store.embed_image(entry.path)
                text_preview = get_file_description(entry)
                face_encodings = get_face_encodings(entry.path)
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
                    face_encodings=face_encodings,
                )
                self.store.add(file_emb)

            self.indexer.mark_indexed(entry.path)

        self._indexing = False
        if self._done_cb:
            self._done_cb(len(self.store))

    def add_named_image(self, path: str, name: str,
                        done_callback: Optional[Callable] = None):
        """Embed a single, user-picked image under a custom name so it can be
        found again quickly by typing that name, without needing to re-scan
        whatever folder it happens to live in. Any face(s) in it become the
        reference for that name, so a later query like "me in the beanie" can
        require the same person, not just any photo with a beanie in it."""
        def worker():
            embedding = self.store.embed_image(path)
            if embedding is not None:
                size_bytes = os.path.getsize(path) if os.path.exists(path) else 0
                self.store.add(FileEmbedding(
                    path=path,
                    name=name,
                    embedding=embedding,
                    file_type="image",
                    text_preview="",
                    size_bytes=size_bytes,
                    face_encodings=get_face_encodings(path),
                ))
            if done_callback:
                done_callback(embedding is not None, name)

        threading.Thread(target=worker, daemon=True).start()

    def _find_referenced_person(self, query_lower: str) -> Optional[Tuple[str, list]]:
        """If the query mentions, as a whole word/phrase, the name of an image
        the user tagged that has a detected face in it, return that name and
        every reference face encoding filed under it (a person can have more
        than one named photo)."""
        by_name: dict = {}
        for e in self.store.embeddings:
            if e.file_type == "image" and e.face_encodings:
                by_name.setdefault(e.name.lower(), []).extend(e.face_encodings)

        for name_lower, encodings in by_name.items():
            if re.search(rf"\b{re.escape(name_lower)}\b", query_lower):
                return name_lower, encodings
        return None

    def _filter_to_same_person(self, results: list, reference_encodings: list) -> list:
        """Narrow (and re-rank) semantic results down to photos of the same
        person as the reference encodings - so "me in the beanie" means the
        beanie photo has to actually be of that person, not just any beanie."""
        matched = []
        for file_emb, score in results:
            distance = best_face_match_distance(reference_encodings, file_emb.face_encodings)
            if distance is None or distance > SAME_PERSON_DISTANCE:
                continue
            face_score = 1.0 - min(distance, 1.0)
            matched.append((file_emb, 0.5 * score + 0.5 * face_score))

        matched.sort(key=lambda pair: pair[1], reverse=True)
        return matched

    def _content_hash(self, path: str) -> Optional[bytes]:
        """Fingerprint of a file's actual bytes, cached per path, so real
        duplicates (the same photo synced into a cloud folder, cached as a
        thumbnail, backed up alongside the original, etc.) can be spotted
        even though they live at different paths and were embedded as
        separate entries."""
        if path in self._hash_cache:
            return self._hash_cache[path]
        try:
            digest = hashlib.sha1()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            result = digest.digest()
        except OSError:
            result = None
        self._hash_cache[path] = result
        return result

    def _dedupe_duplicate_files(self, results: list) -> list:
        """Collapse results that are byte-for-byte the same file so one photo
        doesn't occupy several slots (and crowd out other real matches) just
        because it exists in more than one place on disk. Results are already
        score-sorted, so the first copy of each duplicate group encountered
        is the highest (or equal-highest) scoring one and is kept."""
        seen_hashes = set()
        deduped = []
        for file_emb, score in results:
            content_hash = self._content_hash(file_emb.path)
            if content_hash is not None:
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)
            deduped.append((file_emb, score))
        return deduped

    def _perceptual_hash(self, path: str):
        if path in self._phash_cache:
            return self._phash_cache[path]
        result = get_perceptual_hash(path)
        self._phash_cache[path] = result
        return result

    def _dedupe_near_duplicates(self, results: list) -> list:
        """Collapse different image files that are visually the same picture
        - a resize, recompression, or trivial edit living under a different
        filename - which exact-hash dedup can't catch since the bytes
        differ. Uses a perceptual hash rather than the CLIP embedding used
        for ranking: CLIP reflects semantic content and can drift more
        between a photo and its own recompressed copy than between two
        different-but-similar photos, so it isn't reliable for "is this
        literally the same picture." Results are already score-sorted, so
        the first copy of a group kept is the highest-scoring one."""
        deduped = []
        kept_hashes = []
        for file_emb, score in results:
            if file_emb.file_type == "image":
                phash = self._perceptual_hash(file_emb.path)
                if phash is not None:
                    is_near_duplicate = any(
                        (phash - kept) <= NEAR_DUPLICATE_HASH_DISTANCE
                        for kept in kept_hashes
                    )
                    if is_near_duplicate:
                        continue
                    kept_hashes.append(phash)
            deduped.append((file_emb, score))
        return deduped

    def search(self, query: str, top_k: int = 20) -> List[SearchResult]:
        if not query.strip():
            return []

        query_lower = query.strip().lower()
        # Exact match only - a named image should jump straight to the top when
        # the user types its name, but a sentence that merely mentions the name
        # in passing (e.g. "photo of my passport for the trip") shouldn't force
        # that one file to the top over what the image itself actually matches.
        name_matches = [e for e in self.store.embeddings if e.name.lower() == query_lower]

        query_embedding = self.store.embed_query(query)
        # Widen the pool before any face-identity filtering narrows it back
        # down, so a real match ranked #15 by semantics alone doesn't get cut
        # before the person filter ever sees it.
        pool_k = top_k * 3 if query_embedding is not None else top_k
        semantic_results = self.store.search(query_embedding, top_k=pool_k) if query_embedding is not None else []
        semantic_results = self._dedupe_duplicate_files(semantic_results)
        semantic_results = self._dedupe_near_duplicates(semantic_results)

        person = self._find_referenced_person(query_lower)
        if person is not None and person[0] != query_lower:
            semantic_results = self._filter_to_same_person(semantic_results, person[1])

        seen_paths = set()
        search_results = []

        for file_emb in name_matches:
            if file_emb.path in seen_paths:
                continue
            seen_paths.add(file_emb.path)
            search_results.append(SearchResult(
                path=file_emb.path,
                name=file_emb.name,
                score=1.0,
                file_type=file_emb.file_type,
                text_preview=file_emb.text_preview,
                size_bytes=file_emb.size_bytes,
            ))

        for file_emb, score in semantic_results:
            if file_emb.path in seen_paths:
                continue
            seen_paths.add(file_emb.path)
            search_results.append(SearchResult(
                path=file_emb.path,
                name=file_emb.name,
                score=score,
                file_type=file_emb.file_type,
                text_preview=file_emb.text_preview,
                size_bytes=file_emb.size_bytes,
            ))

        return search_results[:top_k]

    def search_by_image(self, image_path: str, top_k: int = 20) -> List[SearchResult]:
        """Reverse-image search: embed a user-supplied picture in the same
        CLIP space used for indexed images and rank by visual similarity,
        instead of the user having to describe it in words. If the query
        picture has a recognizable face, prefer matches of that same person
        - but only when that actually leaves results, since an incidental
        face (e.g. someone in the background of an object photo) shouldn't
        be able to wipe out otherwise-good visual matches."""
        query_embedding = self.store.embed_image(image_path)
        if query_embedding is None:
            return []

        pool_k = top_k * 3
        results = self.store.search(query_embedding, top_k=pool_k, file_type="image")

        # normcase so "C:\..." and "c:\..." (both valid, e.g. from a file
        # dialog vs. the indexer's own path resolution) compare as the same
        # file on Windows - otherwise the query image's own indexed copy
        # slips through as a "match" and its perfect score buries every
        # other result under it.
        query_key = os.path.normcase(os.path.realpath(image_path))
        results = [(e, s) for e, s in results
                   if os.path.normcase(os.path.realpath(e.path)) != query_key]

        results = self._dedupe_duplicate_files(results)
        results = self._dedupe_near_duplicates(results)

        query_faces = get_face_encodings(image_path)
        if query_faces:
            same_person = self._filter_to_same_person(results, query_faces)
            if same_person:
                results = same_person

        search_results = []
        for file_emb, score in results[:top_k]:
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
