import cv2
import numpy as np
import threading
from pathlib import Path
from typing import Optional, Tuple

from found_it.config import CALIBRATION_DIR, FISHEYE_FOV


class FisheyeDewarp:
    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.map_x: Optional[np.ndarray] = None
        self.map_y: Optional[np.ndarray] = None
        self.calibrated = False

    def load_calibration(self, image_size: Tuple[int, int]) -> bool:
        calib_file = CALIBRATION_DIR / f"calib_camera_{self.camera_id}.npz"
        if not calib_file.exists():
            return False

        data = np.load(str(calib_file))
        K = data["K"]
        D = data["D"]
        w, h = image_size

        balance = 0.0

        new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
            K, D, (w, h), np.eye(3),
            balance=balance
        )

        self.map_x, self.map_y = cv2.fisheye.initUndistortRectifyMap(
            K, D, np.eye(3), new_K, (w, h), cv2.CV_32FC1
        )
        self.calibrated = True
        return True

    def calibrate(self, images: list, image_size: Tuple[int, int],
                  grid: Tuple[int, int] = (6, 9)) -> bool:
        objp = np.zeros((grid[0] * grid[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:grid[1], 0:grid[0]].T.reshape(-1, 2)

        obj_points = []
        img_points = []

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            ret, corners = cv2.findChessboardCorners(gray, grid, None)
            if ret:
                criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
                corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
                obj_points.append(objp)
                img_points.append(corners_refined)

        if len(obj_points) < 3:
            print(f"[Calibration] Camera {self.camera_id}: Not enough valid frames ({len(obj_points)})")
            return False

        w, h = image_size
        K = np.zeros((3, 3))
        D = np.zeros((4, 1))
        flags = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC
        criteria_calib = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-6)

        ret, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
            obj_points, img_points, (w, h), K, D, None, None,
            flags, criteria_calib
        )

        if ret < 0:
            print(f"[Calibration] Camera {self.camera_id}: Calibration failed")
            return False

        CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(str(CALIBRATION_DIR / f"calib_camera_{self.camera_id}.npz"),
                 K=K, D=D)
        print(f"[Calibration] Camera {self.camera_id}: Saved calibration")
        return True

    def dewarp(self, frame: np.ndarray) -> np.ndarray:
        if not self.calibrated:
            return frame
        return cv2.remap(frame, self.map_x, self.map_y, cv2.INTER_LINEAR)


class EquirectangularDewarp:
    """Extracts perspective views from a 360 equirectangular frame."""

    def __init__(self, fov: float = 90.0, num_views: int = 4):
        self.fov = fov
        self.num_views = num_views
        self._maps: list = []
        # dewarp()/dewarp_single() can now be called concurrently - the
        # detection worker thread and the main thread's display cycle both
        # dewarp frames from the same camera - and map-building is lazy on
        # first call, so guard it against a torn/partial build.
        self._maps_lock = threading.Lock()

    def _build_maps(self, equirect_w: int, equirect_h: int,
                    out_w: int, out_h: int):
        self._maps = []
        focal = out_w / (2.0 * np.tan(np.radians(self.fov) / 2.0))

        K = np.array([
            [focal, 0, out_w / 2.0],
            [0, focal, out_h / 2.0],
            [0, 0, 1.0]
        ], dtype=np.float64)

        for i in range(self.num_views):
            yaw = (2.0 * np.pi * i) / self.num_views
            R = self._rotation_matrix(yaw, 0, 0)

            map_x = np.zeros((out_h, out_w), dtype=np.float32)
            map_y = np.zeros((out_h, out_w), dtype=np.float32)

            for v in range(out_h):
                for u in range(out_w):
                    x = (u - out_w / 2.0)
                    y = (v - out_h / 2.0)
                    z = focal

                    vec = np.array([x, y, z], dtype=np.float64)
                    vec = R @ vec
                    vec = vec / np.linalg.norm(vec)

                    theta = np.arcsin(np.clip(vec[1], -1, 1))
                    phi = np.arctan2(vec[0], vec[2])

                    equirect_x = (phi / (2.0 * np.pi) + 0.5) * equirect_w
                    equirect_y = (theta / np.pi + 0.5) * equirect_h

                    map_x[v, u] = np.clip(equirect_x, 0, equirect_w - 1)
                    map_y[v, u] = np.clip(equirect_y, 0, equirect_h - 1)

            self._maps.append((map_x, map_y))

    def _rotation_matrix(self, yaw: float, pitch: float, roll: float):
        cy, sy = np.cos(yaw), np.sin(yaw)
        cp, sp = np.cos(pitch), np.sin(pitch)
        cr, sr = np.cos(roll), np.sin(roll)

        R = np.array([
            [cy * cr + sy * sp * sr, -cy * sr + sy * sp * cr, sy * cp],
            [cp * sr, cp * cr, -sp],
            [-sy * cr + cy * sp * sr, sy * sr + cy * sp * cr, cy * cp]
        ], dtype=np.float64)
        return R

    def _ensure_maps(self, w: int, h: int, out_w: int, out_h: int) -> list:
        with self._maps_lock:
            if not self._maps or self._maps[0][0].shape != (out_h, out_w):
                self._build_maps(w, h, out_w, out_h)
            return self._maps

    def dewarp(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        out_w, out_h = w // 2, h // 2
        maps = self._ensure_maps(w, h, out_w, out_h)

        views = []
        for map_x, map_y in maps:
            view = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_WRAP)
            views.append(view)

        top_row = np.hstack(views[:2])
        bottom_row = np.hstack(views[2:4]) if len(views) > 2 else np.hstack([views[0], views[0]])
        return np.vstack([top_row, bottom_row])

    def dewarp_single(self, frame: np.ndarray, direction_index: int = 0) -> np.ndarray:
        h, w = frame.shape[:2]
        out_w, out_h = w // 2, h // 2
        maps = self._ensure_maps(w, h, out_w, out_h)

        idx = direction_index % len(maps)
        map_x, map_y = maps[idx]
        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_WRAP)
