import os
import re
import hashlib
import threading
from typing import List, Optional, Callable, Tuple
from dataclasses import dataclass

import numpy as np

from found_it.fileindex.indexer import FileIndexer, FileEntry
from found_it.fileindex.store import EmbeddingStore, FileEmbedding, CLIP_MODEL_ID
from found_it.fileindex.index_db import IndexDatabase
from found_it.fileindex.extractor import extract_text_preview, get_file_description
from found_it.fileindex.faces import (
    get_face_encodings, get_faces_with_locations, best_face_match_distance, SAME_PERSON_DISTANCE
)
from found_it.fileindex.people import PersonClusterer, save_face_thumbnail
from found_it.fileindex.phash import get_perceptual_hash, NEAR_DUPLICATE_HASH_DISTANCE

# A fixed absolute CLIP similarity cutoff doesn't generalize: it's dataset-
# dependent (it drifts with the CLIP model, and even with a person's own
# photo mix) and empirically, a small personal photo set is often too
# visually homogeneous for CLIP to give a query a *low* absolute score just
# because it's implausible - everything about "a person" scores in a similar
# narrow band. Instead, score each candidate as a z-score relative to that
# person's *own* score distribution for this specific query: how much better
# than a typical photo of them this one is. MIN_DESCRIPTION_Z_SCORE is how
# many standard deviations above their own mean a photo must be to count as
# "notably matching" rather than just average.
MIN_DESCRIPTION_Z_SCORE = 1.0
# Beyond clearing the bar above, also require staying within this fraction
# of the best match found for that person, so results don't get padded out
# with photos only weakly related once a much better match exists.
MIN_RELATIVE_TO_BEST_MATCH = 0.90


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
        self.store = EmbeddingStore()
        # Persistence (files, faces, people) lives here, not in EmbeddingStore -
        # that class is also used standalone by DeviceScanner for ephemeral,
        # per-connection ADB file search, which must never be written to or
        # mixed with the durable desktop index.
        self.index_db = IndexDatabase()
        self._ensure_clip_model_current()
        self._load_persisted_index()
        self.indexer = FileIndexer(is_current=self.index_db.file_up_to_date)
        self.clusterer = PersonClusterer(self.index_db)
        self._indexing = False
        self._cancel_requested = False
        self._progress_cb: Optional[Callable] = None
        self._done_cb: Optional[Callable] = None
        self._hash_cache: dict = {}
        self._phash_cache: dict = {}

    def _ensure_clip_model_current(self):
        """If the CLIP model has changed since the index was last built
        (see CLIP_MODEL_ID), every image's stored embedding is now in a
        different, incompatible vector space - null them out so they're
        recomputed on the next scan, without touching faces/people, since
        face detection doesn't depend on the CLIP model at all."""
        if self.index_db.get_meta("clip_model") != CLIP_MODEL_ID:
            self.index_db.null_image_embeddings()
            self.index_db.set_meta("clip_model", CLIP_MODEL_ID)

    def _load_persisted_index(self):
        """Repopulate the in-memory store (and its numpy similarity search)
        from disk, so previously indexed files, embeddings, and detected
        faces survive an app restart instead of requiring a full rescan."""
        for row in self.index_db.load_all_file_embeddings():
            self.store.add(FileEmbedding(
                path=row["path"],
                name=row["name"],
                embedding=row["embedding"],
                file_type=row["file_type"],
                text_preview=row["text_preview"],
                size_bytes=row["size_bytes"],
                modified_time=row["modified_time"],
                face_encodings=row["face_encodings"],
            ))

    def _persist(self, file_emb: FileEmbedding) -> int:
        """Add a file to the in-memory store and to disk, returning the
        database file id so callers (e.g. face detection) can link related
        rows, such as faces, to this file."""
        self.store.add(file_emb)
        return self.index_db.upsert_file(
            path=file_emb.path,
            name=file_emb.name,
            file_type=file_emb.file_type,
            text_preview=file_emb.text_preview,
            size_bytes=file_emb.size_bytes,
            modified_time=file_emb.modified_time,
            embedding=file_emb.embedding,
        )

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
            faces_found = []

            if entry.is_image:
                embedding = self.store.embed_image(entry.path)
                text_preview = get_file_description(entry)
                faces_found = get_faces_with_locations(entry.path)
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
                    face_encodings=[enc for enc, _bbox in faces_found],
                )
                file_id = self._persist(file_emb)
                self._process_faces(file_id, entry.path, faces_found)

            self.indexer.mark_indexed(entry.path)

        self._indexing = False
        if self._done_cb:
            self._done_cb(len(self.store))

    def _process_faces(self, file_id: int, image_path: str, faces_found: list) -> list:
        """Cluster every face detected in a just-indexed file into a person
        (existing or new) and persist a cropped thumbnail for the gallery.
        Clears any faces left over from a previous version of this file
        first, since a changed file is re-embedded (and re-faced) fresh.
        Returns the assigned person id for each face, in the same order as
        faces_found."""
        if not faces_found:
            return []
        self.index_db.delete_faces_for_file(file_id)
        person_ids = []
        for encoding, bbox in faces_found:
            person_id = self.clusterer.assign(encoding)
            thumbnail_path = save_face_thumbnail(image_path, bbox)
            self.index_db.add_face(file_id, person_id, encoding, bbox, thumbnail_path)
            if thumbnail_path is not None:
                self.index_db.set_person_thumbnail(person_id, thumbnail_path)
            person_ids.append(person_id)
        return person_ids

    @staticmethod
    def _largest_face_index(faces_found: list) -> int:
        def area(item):
            _encoding, (top, right, bottom, left) = item
            return (bottom - top) * (right - left)
        return max(range(len(faces_found)), key=lambda i: area(faces_found[i]))

    def _index_picked_image(self, image_path: str):
        """Embed and persist a user-picked image (outside the normal folder
        scan) and return (file_id, faces_found), so a caller can link one of
        its faces to a person. None if the image can't be embedded."""
        embedding = self.store.embed_image(image_path)
        if embedding is None:
            return None
        faces_found = get_faces_with_locations(image_path)
        size_bytes = os.path.getsize(image_path) if os.path.exists(image_path) else 0
        file_emb = FileEmbedding(
            path=image_path,
            name=os.path.basename(image_path),
            embedding=embedding,
            file_type="image",
            size_bytes=size_bytes,
            face_encodings=[enc for enc, _bbox in faces_found],
        )
        file_id = self._persist(file_emb)
        return file_id, faces_found

    def add_person_from_image(self, image_path: str, name: str) -> Optional[int]:
        """Manually seed (or match into) a person from one picked photo, for
        tagging someone before a folder scan reaches their photos. Uses the
        largest face in the image. Returns the named person's id, or None
        if no face was found."""
        indexed = self._index_picked_image(image_path)
        if indexed is None:
            return None
        file_id, faces_found = indexed
        if not faces_found:
            return None

        person_ids = self._process_faces(file_id, image_path, faces_found)
        idx = self._largest_face_index(faces_found)
        person_id = person_ids[idx]
        self.rename_person(person_id, name)
        return person_id

    def add_file_to_person(self, image_path: str, person_id: int) -> bool:
        """Manually attach a photo to an existing person, for a face the
        automatic scan missed or clustered separately (e.g. an unusual
        angle or lighting) - bypasses the usual same-person distance check
        since the user is confirming the match directly."""
        indexed = self._index_picked_image(image_path)
        if indexed is None:
            return False
        file_id, faces_found = indexed
        if not faces_found:
            return False

        self.index_db.delete_faces_for_file(file_id)
        idx = self._largest_face_index(faces_found)
        encoding, bbox = faces_found[idx]
        self.clusterer.force_assign(encoding, person_id)
        thumbnail_path = save_face_thumbnail(image_path, bbox)
        self.index_db.add_face(file_id, person_id, encoding, bbox, thumbnail_path)
        if thumbnail_path is not None:
            self.index_db.set_person_thumbnail(person_id, thumbnail_path)
        return True

    def get_people(self) -> list:
        """Every detected person with at least one face, most-photographed
        first, as dicts with id/name/thumbnail_path/face_count."""
        return self.index_db.get_people()

    def rename_person(self, person_id: int, name: str):
        self.index_db.rename_person(person_id, name)

    def delete_person(self, person_id: int):
        """Remove a person and their face records entirely - e.g. a
        mis-clustered "person" that isn't really a distinct individual, or
        one the user just doesn't want tracked. The underlying photos stay
        indexed and searchable; they just won't show up under this identity
        anymore, and could form a new person if rescanned later."""
        thumbnails = set(self.index_db.get_face_thumbnails_for_person(person_id))
        person = next((p for p in self.get_people() if p["id"] == person_id), None)
        if person and person.get("thumbnail_path"):
            thumbnails.add(person["thumbnail_path"])

        self.index_db.delete_person(person_id)
        self.clusterer.forget(person_id)

        for path in thumbnails:
            try:
                os.remove(path)
            except OSError:
                pass

    def search_person_by_description(self, query: str, top_k: int = 20):
        """Given a query naming a known person plus a free-text description
        of what they're wearing/doing - e.g. "Riddeck wearing a blue
        jacket" - resolve which person is meant, restrict candidates to
        their own linked photos (not just whatever else CLIP thinks is
        relevant across the whole index), and rank just those by how well
        the description alone matches, with the name itself stripped out
        first since it's a meaningless token to CLIP and would only dilute
        the match. Returns (person_id, person_name, results), or None if no
        known person's name appears in the query."""
        query_lower = query.strip().lower()
        match = None
        for name, _centroid in self.index_db.get_named_people():
            found = re.search(rf"\b{re.escape(name.lower())}\b", query_lower)
            # Prefer the longest matching name, in case one name is a
            # substring of another (e.g. "Alex" inside "Alexander").
            if found and (match is None or len(name) > len(match[0])):
                match = (name, found)
        if match is None:
            return None

        name, found = match
        person_id = self.index_db.get_person_id_by_name(name)
        if person_id is None:
            return None

        description = (query[:found.start()] + query[found.end():]).strip(" ,.!?'\"")
        if not description:
            return person_id, name, self.get_files_for_person(person_id)[:top_k]

        query_embedding = self.store.embed_query(description)
        if query_embedding is None:
            return person_id, name, self.get_files_for_person(person_id)[:top_k]

        person_paths = {row["path"] for row in self.index_db.get_files_for_person(person_id)}
        candidates = [e for e in self.store.embeddings if e.path in person_paths]
        if not candidates:
            return person_id, name, []

        raw_scores = np.array([float(e.embedding @ query_embedding) for e in candidates])
        mean, std = float(raw_scores.mean()), float(raw_scores.std())
        top_score = float(raw_scores.max())

        # Drop anything that isn't a real match for the description: not
        # notably better than a typical photo of this person for this query
        # (z-score against their own distribution, not a fixed number - see
        # MIN_DESCRIPTION_Z_SCORE), or too far behind the single best match
        # found among their photos.
        kept = []
        for e, score in zip(candidates, raw_scores):
            z = (score - mean) / std if std > 1e-6 else 0.0
            if z >= MIN_DESCRIPTION_Z_SCORE and (top_score <= 0 or score >= top_score * MIN_RELATIVE_TO_BEST_MATCH):
                kept.append((e, float(score)))
        kept.sort(key=lambda pair: pair[1], reverse=True)

        results = [
            SearchResult(
                path=e.path, name=e.name, score=score, file_type=e.file_type,
                text_preview=e.text_preview, size_bytes=e.size_bytes,
            )
            for e, score in kept[:top_k]
        ]
        return person_id, name, results

    def get_files_for_person(self, person_id: int) -> List[SearchResult]:
        rows = self.index_db.get_files_for_person(person_id)
        return [
            SearchResult(
                path=row["path"],
                name=row["name"],
                score=1.0,
                file_type=row["file_type"] or "image",
                text_preview=row["text_preview"] or "",
                size_bytes=row["size_bytes"] or 0,
            )
            for row in rows
        ]

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
                self._persist(FileEmbedding(
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
        """If the query mentions, as a whole word/phrase, the name of a
        person from the People gallery, return that name and their cluster
        centroid as the reference encoding - built from every one of their
        detected photos, not just a single tagged one. Falls back to the
        older per-image tagging ("+ Add Image") for named files that aren't
        faces at all, e.g. "Passport"."""
        for name, centroid in self.index_db.get_named_people():
            name_lower = name.lower()
            if re.search(rf"\b{re.escape(name_lower)}\b", query_lower):
                return name_lower, [centroid]

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
