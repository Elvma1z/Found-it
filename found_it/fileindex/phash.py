from typing import Optional

_imagehash = None
_load_attempted = False

# Hamming distance (out of 64 bits) below which two images are treated as
# the same picture - a resize, recompression, or trivial edit. A real
# resize+recompress round-trip typically lands at 0-3; a genuinely
# different photo typically lands well above 20, so this leaves a wide
# safety margin in both directions.
NEAR_DUPLICATE_HASH_DISTANCE = 6


def _load():
    global _imagehash, _load_attempted
    if _load_attempted:
        return _imagehash
    _load_attempted = True
    try:
        import imagehash
        _imagehash = imagehash
    except ImportError:
        print("[PHash] imagehash not installed. Near-duplicate detection disabled.")
        print("  Install with: pip install ImageHash")
    except Exception as e:
        print(f"[PHash] Failed to load imagehash: {e}")
    return _imagehash


def get_perceptual_hash(image_path: str) -> Optional["object"]:
    """A fingerprint of an image's visual content that's robust to resizing,
    recompression, and minor edits - unlike a CLIP embedding, which reflects
    semantic content and can drift more between a photo and its own
    recompressed copy than between two different-but-similar photos. None if
    the library isn't installed or the file can't be read."""
    ih = _load()
    if ih is None:
        return None
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return ih.phash(img)
    except Exception:
        return None
