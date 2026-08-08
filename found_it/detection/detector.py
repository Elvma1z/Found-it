import cv2
import numpy as np
from pathlib import Path
from typing import List, Optional

from found_it.config import YOLO_MODEL, DETECTION_CONFIDENCE, DETECTION_IMGSZ, SNAPSHOTS_DIR


class ItemDetector:
    def __init__(self):
        self.model = None
        self.device = "cpu"
        self.half = False
        self._load_model()

    def _load_model(self):
        try:
            from ultralytics import YOLO
            self.model = YOLO(YOLO_MODEL)

            try:
                import torch
                if torch.cuda.is_available():
                    self.device = 0
                    self.half = True
            except ImportError:
                pass

            print(f"[Detector] Loaded model: {YOLO_MODEL} (device={self.device}, half={self.half})")
        except ImportError:
            print("[Detector] ultralytics not installed. Run: pip install ultralytics")
        except Exception as e:
            print(f"[Detector] Failed to load model: {e}")

    def detect(self, frame: np.ndarray, camera_id: int,
               confidence: float = DETECTION_CONFIDENCE) -> List[dict]:
        """Run inference and return detections. Snapshot crops are NOT saved
        here - only the caller knows whether a detection is a brand-new item
        worth writing to disk versus an already-tracked one re-detected on
        this cycle, so snapshotting is left to save_snapshot()."""
        if self.model is None:
            return []

        kwargs = {"device": self.device}
        if self.half:
            kwargs["half"] = True
        results = self.model(frame, conf=confidence, imgsz=DETECTION_IMGSZ, verbose=False, **kwargs)
        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = self.model.names[cls_id]

                h, w = frame.shape[:2]
                center_x = (x1 + x2) / 2 / w
                center_y = (y1 + y2) / 2 / h

                detections.append({
                    "label": label,
                    "confidence": conf,
                    "camera_id": camera_id,
                    "zone_x": center_x,
                    "zone_y": center_y,
                    "bbox_x1": x1,
                    "bbox_y1": y1,
                    "bbox_x2": x2,
                    "bbox_y2": y2,
                })

        return detections

    def save_snapshot(self, frame: np.ndarray, y1: int, y2: int,
                       x1: int, x2: int, label: str,
                       camera_id: int) -> Optional[str]:
        try:
            padding = 10
            h, w = frame.shape[:2]
            crop = frame[
                max(0, y1 - padding):min(h, y2 + padding),
                max(0, x1 - padding):min(w, x2 + padding)
            ]
            if crop.size == 0:
                return None

            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            import time
            filename = f"{label}_cam{camera_id}_{int(time.time())}.jpg"
            path = SNAPSHOTS_DIR / filename
            cv2.imwrite(str(path), crop)
            return str(path)
        except Exception:
            return None

    def annotate(self, frame: np.ndarray, detections: List[dict]) -> np.ndarray:
        annotated = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = det["bbox_x1"], det["bbox_y1"], det["bbox_x2"], det["bbox_y2"]
            label = det["label"]
            conf = det["confidence"]

            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)

            text = f"{label} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 10), (x1 + tw, y1), (0, 255, 0), -1)
            cv2.putText(annotated, text, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        return annotated
