import numpy as np
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class FileEmbedding:
    path: str
    name: str
    embedding: np.ndarray
    file_type: str
    text_preview: str = ""
    size_bytes: int = 0
    modified_time: float = 0
    face_encodings: List[np.ndarray] = field(default_factory=list)


class EmbeddingStore:
    def __init__(self):
        self.embeddings: List[FileEmbedding] = []
        self._clip_model = None
        self._clip_processor = None
        self._text_model = None
        self._text_tokenizer = None

    def _load_clip(self):
        if self._clip_model is not None:
            return
        try:
            import open_clip
            self._clip_model, _, self._clip_processor = open_clip.create_model_and_transforms(
                "RN50", pretrained="openai"
            )
            self._clip_tokenizer = open_clip.get_tokenizer("RN50")
            self._clip_model.eval()
            print("[Extractor] CLIP model loaded")
        except ImportError:
            print("[Extractor] open_clip not installed. Image search disabled.")
            print("  Install with: pip install open-clip-torch")
        except Exception as e:
            print(f"[Extractor] Failed to load CLIP: {e}")

    def _load_text_model(self):
        if self._text_model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._text_model = SentenceTransformer("all-MiniLM-L6-v2")
            print("[Extractor] Text embedding model loaded")
        except ImportError:
            print("[Extractor] sentence-transformers not installed.")
            print("  Install with: pip install sentence-transformers")
        except Exception as e:
            print(f"[Extractor] Failed to load text model: {e}")

    def embed_image(self, image_path: str) -> Optional[np.ndarray]:
        self._load_clip()
        if self._clip_model is None:
            return None

        try:
            from PIL import Image
            import torch

            img = Image.open(image_path).convert("RGB")
            image_input = self._clip_processor(img).unsqueeze(0)

            with torch.no_grad():
                features = self._clip_model.encode_image(image_input)

            features = features / features.norm(dim=-1, keepdim=True)
            return features.squeeze().numpy()
        except Exception as e:
            print(f"[Extractor] Failed to embed image {image_path}: {e}")
            return None

    def embed_text(self, text: str) -> Optional[np.ndarray]:
        self._load_text_model()
        if self._text_model is None:
            return None

        try:
            embedding = self._text_model.encode(text, convert_to_numpy=True)
            return embedding / np.linalg.norm(embedding)
        except Exception as e:
            print(f"[Extractor] Failed to embed text: {e}")
            return None

    def embed_query(self, query: str) -> Optional[np.ndarray]:
        self._load_clip()
        self._load_text_model()

        if self._clip_model is not None:
            try:
                import torch
                text_input = self._clip_tokenizer([query])
                with torch.no_grad():
                    features = self._clip_model.encode_text(text_input)
                features = features / features.norm(dim=-1, keepdim=True)
                return features.squeeze().numpy()
            except Exception:
                pass

        if self._text_model is not None:
            return self.embed_text(query)

        return None

    def add(self, file_embedding: FileEmbedding):
        self.embeddings.append(file_embedding)

    def remove(self, path: str):
        self.embeddings = [e for e in self.embeddings if e.path != path]

    def search(self, query_embedding: np.ndarray,
               top_k: int = 20, file_type: Optional[str] = None) -> List[tuple]:
        candidates = [e for e in self.embeddings
                      if file_type is None or e.file_type == file_type]
        if not candidates:
            return []

        stored = np.array([e.embedding for e in candidates])

        similarities = stored @ query_embedding

        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            results.append((candidates[idx], float(similarities[idx])))

        return results

    def clear(self):
        self.embeddings.clear()

    def __len__(self):
        return len(self.embeddings)
