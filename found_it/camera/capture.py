import cv2
import numpy as np
import time
import threading
import platform
from typing import Callable, List, Optional, Tuple

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

    def start(self, open_attempts: int = 3) -> bool:
        # DirectShow devices (especially one that another handle - e.g. a
        # camera discovery probe - just opened and released a moment ago)
        # can report isOpened() successfully before the hardware is truly
        # ready to deliver frames. Confirm a real frame actually comes
        # through before declaring the camera started, retrying the open a
        # few times first, so callers don't end up stuck on "No signal"
        # forever for a camera that just needed a beat to become available.
        for attempt in range(1, open_attempts + 1):
            if not self._open():
                time.sleep(0.3)
                continue

            ret, frame = self.cap.read()
            if ret and frame is not None:
                self.frame = frame
                break

            print(f"[Camera {self.camera_id}] Opened but not delivering frames yet "
                  f"(attempt {attempt}/{open_attempts}), retrying...")
            self.cap.release()
            self.cap = None
            time.sleep(0.3)
        else:
            print(f"[Camera {self.camera_id}] Failed to open camera")
            return False

        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        print(f"[Camera {self.camera_id}] Started")
        return True

    def _open(self) -> bool:
        # DirectShow opens/reads faster than Windows' default MSMF backend
        # for most webcams; fall back to the default backend if it can't
        # open the device that way.
        if platform.system() == "Windows":
            self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap.release()
                self.cap = cv2.VideoCapture(self.camera_id)
        else:
            self.cap = cv2.VideoCapture(self.camera_id)

        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            return False

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
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


def probe_camera(camera_id: int) -> Optional[dict]:
    """Briefly try to open a device index to see if a camera is actually
    there, without keeping it open. An index already claimed by another
    open handle (e.g. one of this app's own active room cameras) will
    correctly fail to open a second time on most backends/drivers, so it's
    naturally skipped rather than reported as newly available."""
    if platform.system() == "Windows":
        cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(camera_id)
    else:
        cap = cv2.VideoCapture(camera_id)

    if not cap.isOpened():
        cap.release()
        return None

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"id": camera_id, "width": width, "height": height}


class CameraDiscovery:
    """Scans device indices in the background for cameras that aren't
    already configured, so a room can be set up without guessing an ID by
    trial and error."""

    def __init__(self):
        self._scanning = False

    def is_scanning(self) -> bool:
        return self._scanning

    def start_scan(self, max_index: int = 10, exclude_ids: Optional[set] = None,
                    progress_callback: Optional[Callable[[str], None]] = None,
                    done_callback: Optional[Callable[[List[dict]], None]] = None):
        if self._scanning:
            return
        self._scanning = True
        thread = threading.Thread(
            target=self._scan_worker,
            args=(max_index, exclude_ids or set(), progress_callback, done_callback),
            daemon=True,
        )
        thread.start()

    def _scan_worker(self, max_index, exclude_ids, progress_callback, done_callback):
        found = []
        for camera_id in range(max_index):
            if camera_id in exclude_ids:
                continue
            if progress_callback:
                progress_callback(f"Checking camera {camera_id}...")
            info = probe_camera(camera_id)
            if info:
                found.append(info)
        self._scanning = False
        if done_callback:
            done_callback(found)
