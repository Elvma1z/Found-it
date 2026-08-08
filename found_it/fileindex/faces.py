from typing import List, Optional

import numpy as np

_face_recognition = None
_load_attempted = False

# face_recognition's own docs call ~0.6 the standard cutoff for "same person" -
# below it two encodings are considered a confident match, above it different people.
SAME_PERSON_DISTANCE = 0.6


def _load():
    global _face_recognition, _load_attempted
    if _load_attempted:
        return _face_recognition
    _load_attempted = True
    try:
        import face_recognition
        _face_recognition = face_recognition
    except ImportError:
        print("[Faces] face_recognition not installed. Same-person matching disabled.")
        print("  Install with: pip install face_recognition")
    except Exception as e:
        print(f"[Faces] Failed to load face_recognition: {e}")
    return _face_recognition


def get_face_encodings(image_path: str) -> List[np.ndarray]:
    """One 128-d encoding per face detected in the image. Empty if the library
    isn't installed, the file isn't readable, or no faces were found."""
    fr = _load()
    if fr is None:
        return []
    try:
        image = fr.load_image_file(image_path)
        locations = fr.face_locations(image)
        if not locations:
            return []
        return fr.face_encodings(image, known_face_locations=locations)
    except Exception:
        return []


def best_face_match_distance(reference_encodings: List[np.ndarray],
                             candidate_encodings: List[np.ndarray]) -> Optional[float]:
    """Smallest distance between any reference face and any candidate face -
    lower means more likely the same person. None if either side has no faces
    or the library isn't available."""
    if not reference_encodings or not candidate_encodings:
        return None
    fr = _load()
    if fr is None:
        return None

    best = None
    for ref in reference_encodings:
        distances = fr.face_distance(candidate_encodings, ref)
        if len(distances) == 0:
            continue
        local_best = float(min(distances))
        if best is None or local_best < best:
            best = local_best
    return best
