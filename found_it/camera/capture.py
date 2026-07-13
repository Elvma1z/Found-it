import cv2
import numpy as np
import time
import threading
from typing import Optional, Tuple

from found_it.config import CAMERA_RESOLUTION, CAMERA_FPS


class CameraCapture:
    def __init__(self, camera_id: int, resolution: Tuple[int, int] = CAMERA_RESOLUTION):
        self.camera_id = camera_id
        self.resolution = resolution
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame: Optional[np.ndarray] = None
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            print(f"[Camera {self.camera_id}] Failed to open camera")
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)

        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        print(f"[Camera {self.camera_id}] Started")
        return True

    def _capture_loop(self):
        while self.running and self.cap is not None:
            ret, frame = self.cap.read()
            if ret:
                with self._lock:
                    self.frame = frame
            else:
                time.sleep(0.01)

    def get_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            if self.frame is not None:
                return self.frame.copy()
        return None

    def stop(self):
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        print(f"[Camera {self.camera_id}] Stopped")

    def is_active(self) -> bool:
        return self.running and self.cap is not None and self.cap.isOpened()
