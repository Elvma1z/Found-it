import math
from typing import List, Optional, Tuple

from found_it.storage.models import DetectedItem, RoomConfig


class ItemMapper:
    def __init__(self, room_config: RoomConfig):
        self.room = room_config

    def get_camera(self, camera_id: int) -> Optional[dict]:
        for cam in self.room.cameras:
            if cam["id"] == camera_id:
                return cam
        return None

    def pixel_to_room(self, zone_x: float, zone_y: float,
                      camera_id: int) -> Tuple[float, float]:
        cam = self.get_camera(camera_id)
        cam_x = cam["x"] if cam else self.room.width_m / 2.0
        cam_y = cam["y"] if cam else self.room.height_m / 2.0

        # Objects are positioned relative to wherever the camera actually
        # sits in the room: each detection is an offset from the camera's
        # placed (x, y), scaled by the room size, and clamped to the room.
        room_x = cam_x + (zone_x - 0.5) * self.room.width_m
        room_y = cam_y + (zone_y - 0.5) * self.room.height_m

        room_x = max(0.0, min(self.room.width_m, room_x))
        room_y = max(0.0, min(self.room.height_m, room_y))

        return (room_x, room_y)

    def room_to_map_coords(self, room_x: float, room_y: float,
                           map_width: int, map_height: int) -> Tuple[int, int]:
        mx = int((room_x / self.room.width_m) * map_width)
        my = int((room_y / self.room.height_m) * map_height)
        return (mx, my)

    def merge_detections(self, all_detections: List[List[dict]]) -> List[dict]:
        if not all_detections:
            return []

        merged = []
        tolerance = 0.2
        used = [set() for _ in all_detections]

        for i, dets_a in enumerate(all_detections):
            for j, det_a in enumerate(dets_a):
                best_match = None
                best_cam = -1
                best_idx = -1

                for k, dets_b in enumerate(all_detections):
                    if k == i:
                        continue
                    for l, det_b in enumerate(dets_b):
                        if l in used[k]:
                            continue
                        if det_a["label"] == det_b["label"]:
                            room_a = self.pixel_to_room(
                                det_a["zone_x"], det_a["zone_y"], det_a["camera_id"]
                            )
                            room_b = self.pixel_to_room(
                                det_b["zone_x"], det_b["zone_y"], det_b["camera_id"]
                            )
                            dist = math.sqrt(
                                (room_a[0] - room_b[0]) ** 2 +
                                (room_a[1] - room_b[1]) ** 2
                            )
                            if dist < tolerance * self.room.width_m:
                                if det_b["confidence"] > (best_match["confidence"] if best_match else 0):
                                    best_match = det_b
                                    best_cam = k
                                    best_idx = l

                if best_match is not None:
                    used[best_cam].add(best_idx)
                    if best_match["confidence"] > det_a["confidence"]:
                        merged.append(best_match)
                        used[i].add(j)
                        continue

                if j not in used[i]:
                    merged.append(det_a)
                    used[i].add(j)

        return merged

    def get_zone_name(self, room_x: float, room_y: float) -> str:
        for zone in self.room.zones:
            if (zone["x1"] <= room_x <= zone["x2"] and
                    zone["y1"] <= room_y <= zone["y2"]):
                return zone["name"]

        rel_x = room_x / self.room.width_m
        rel_y = room_y / self.room.height_m

        if rel_x < 0.33:
            col = "left"
        elif rel_x < 0.66:
            col = "center"
        else:
            col = "right"

        if rel_y < 0.33:
            row = "top"
        elif rel_y < 0.66:
            row = "middle"
        else:
            row = "bottom"

        return f"{row}-{col}"
