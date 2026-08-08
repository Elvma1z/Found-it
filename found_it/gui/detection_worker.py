from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class DetectionWorker(QObject):
    """Runs camera capture -> dewarp -> YOLO inference -> multi-camera merge
    off the GUI thread, so a slow inference pass no longer freezes the UI.

    Only reads shared state (room profiles/cameras/dewarpers/mappers) that
    the main thread owns and mutates in place rather than reassigning, so
    the references handed to this worker never go stale. DB writes and any
    Qt widget access happen back on the main thread via cycle_done, since
    sqlite connections and widgets aren't safe to touch from a worker thread.
    """

    cycle_done = pyqtSignal(list, int)

    def __init__(self, detector, app_settings):
        super().__init__()
        self.detector = detector
        self.app_settings = app_settings
        self.dewarp_enabled = app_settings.dewarp_default
        self.room_profiles = []
        self.room_cameras = {}
        self.room_dewarpers = {}
        self.room_mappers = {}
        self._timer = None
        self._frame_count = 0

    def start(self, interval_ms: int = 100):
        # Created here rather than in __init__ so the QTimer is owned by
        # whichever thread this worker has been moved to by the time
        # start() actually runs (its timeout fires on that thread's loop).
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(interval_ms)

    def _on_timer(self):
        self._frame_count += 1
        if self._frame_count % max(1, self.app_settings.detection_frame_skip) != 0:
            return
        self.run_cycle()

    def run_cycle(self):
        results = []
        total_detections = 0

        for profile in list(self.room_profiles):
            cams = self.room_cameras.get(profile.id, {})
            if not cams:
                continue
            dewarpers = self.room_dewarpers.get(profile.id, {})
            mapper = self.room_mappers.get(profile.id)
            if mapper is None:
                continue

            all_detections_per_cam = []
            frames_by_cam = {}
            for cam_id, cam in list(cams.items()):
                frame = cam.get_frame()
                if frame is None:
                    continue

                if self.dewarp_enabled and cam_id in dewarpers:
                    frame = dewarpers[cam_id].dewarp(frame)

                frames_by_cam[cam_id] = frame
                detections = self.detector.detect(
                    frame, cam_id, confidence=self.app_settings.detection_confidence
                )
                all_detections_per_cam.append(detections)

            merged = mapper.merge_detections(all_detections_per_cam)
            total_detections += len(merged)
            results.append((profile.id, merged, frames_by_cam))

        self.cycle_done.emit(results, total_detections)
