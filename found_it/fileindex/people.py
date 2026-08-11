import uuid
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from found_it.fileindex.faces import SAME_PERSON_DISTANCE
from found_it.config import FACES_DIR


class PersonClusterer:
    """Incrementally groups face encodings into people. Each person is
    represented by a running-average centroid of every face assigned to
    them so far; a new face joins whichever person's centroid it's closest
    to (the same Euclidean distance and 0.6 threshold face_recognition
    itself uses for "same person" - see SAME_PERSON_DISTANCE), or starts a
    brand new (unnamed) person if none are close enough. Centroid state is
    seeded from the database on construction so clustering stays consistent
    across app restarts and incremental rescans."""

    def __init__(self, index_db):
        self.db = index_db
        self._centroids = index_db.get_person_centroids()  # {person_id: (centroid, count)}

    def assign(self, encoding: np.ndarray) -> int:
        best_id, best_dist = None, None
        for person_id, (centroid, _count) in self._centroids.items():
            dist = float(np.linalg.norm(centroid - encoding))
            if best_dist is None or dist < best_dist:
                best_id, best_dist = person_id, dist

        if best_id is not None and best_dist <= SAME_PERSON_DISTANCE:
            centroid, count = self._centroids[best_id]
            new_count = count + 1
            new_centroid = (centroid * count + encoding) / new_count
            self._centroids[best_id] = (new_centroid, new_count)
            self.db.update_person_centroid(best_id, new_centroid, new_count)
            return best_id

        person_id = self.db.create_person()
        self._centroids[person_id] = (encoding.copy(), 1)
        self.db.update_person_centroid(person_id, encoding, 1)
        return person_id

    def force_assign(self, encoding: np.ndarray, person_id: int) -> int:
        """Fold a face into a specific person's centroid without the usual
        distance check - for when the user manually confirms a match
        (e.g. via the People tab's "+ Add File") that automatic clustering
        missed or split off."""
        if person_id in self._centroids:
            centroid, count = self._centroids[person_id]
            new_count = count + 1
            new_centroid = (centroid * count + encoding) / new_count
        else:
            new_centroid, new_count = encoding.copy(), 1
        self._centroids[person_id] = (new_centroid, new_count)
        self.db.update_person_centroid(person_id, new_centroid, new_count)
        return person_id

    def forget(self, person_id: int):
        """Drop a deleted person from in-memory clustering state, so a face
        detected later in this session isn't matched against a centroid
        that no longer exists in the database - which would violate the
        faces.person_id foreign key when it's persisted."""
        self._centroids.pop(person_id, None)


def save_face_thumbnail(image_path: str, bbox: Tuple[int, int, int, int]) -> Optional[Path]:
    """Crop a detected face (bbox = face_recognition's own (top, right,
    bottom, left) convention) out of its source image, with a margin, and
    save it as a small JPG for use as a gallery thumbnail. Returns the
    saved path, or None if the crop/save failed."""
    try:
        from PIL import Image
        top, right, bottom, left = bbox
        margin = int((bottom - top) * 0.4)
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            box = (
                max(0, left - margin), max(0, top - margin),
                min(w, right + margin), min(h, bottom + margin),
            )
            crop = img.crop(box)
            crop.thumbnail((256, 256))
            FACES_DIR.mkdir(parents=True, exist_ok=True)
            dest = FACES_DIR / f"{uuid.uuid4().hex}.jpg"
            crop.save(dest, "JPEG", quality=88)
            return dest
    except Exception:
        return None
