"""ByteTrack/BoT-SORT de Ultralytics con expiración por tiempo real."""

import math
from types import SimpleNamespace

import numpy as np

from camera_counter.config import Config
from camera_counter.detection.detector import configure_ultralytics
from camera_counter.types import Detection, TrackedPerson


class PersonTracker:
    def __init__(self, config: Config):
        configure_ultralytics(config)
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.bot_sort import BOTSORT
        from ultralytics.trackers.byte_tracker import BYTETracker

        cfg = config.tracking
        args = SimpleNamespace(
            tracker_type=cfg.type,
            track_high_thresh=cfg.high_threshold,
            track_low_thresh=cfg.low_threshold,
            new_track_thresh=cfg.new_threshold,
            track_buffer=math.ceil(config.camera.fps * cfg.max_lost_seconds) + 1,
            match_thresh=cfg.match_threshold,
            fuse_score=True,
            gmc_method="none",
            proximity_thresh=0.5,
            appearance_thresh=0.8,
            with_reid=False,
            model="auto",
        )
        self.engine = BYTETracker(args) if cfg.type == "bytetrack" else BOTSORT(args)
        self.Boxes = Boxes
        self.max_lost_seconds = cfg.max_lost_seconds
        self.max_tracks = cfg.max_tracks
        self.last_seen: dict[int, float] = {}
        self.name = cfg.type

    def _expire(self, now: float) -> None:
        for name in ("tracked_stracks", "lost_stracks"):
            keep = []
            for track in getattr(self.engine, name):
                if now - self.last_seen.get(track.track_id, now) > self.max_lost_seconds:
                    track.mark_removed()
                else:
                    keep.append(track)
            setattr(self.engine, name, keep)
        active = self.engine.tracked_stracks + self.engine.lost_stracks
        ids = {track.track_id for track in active}
        self.last_seen = {key: value for key, value in self.last_seen.items() if key in ids}

    def update(self, detections: list[Detection], image, now: float) -> list[TrackedPerson]:
        self._expire(now)
        rows = [
            [*item.box, item.confidence, 0]
            for item in detections
            if item.class_id == 0
            and all(math.isfinite(v) for v in (*item.box, item.confidence))
            and item.box[2] > item.box[0]
            and item.box[3] > item.box[1]
        ]
        boxes = self.Boxes(np.asarray(rows, dtype=np.float32).reshape(-1, 6), image.shape[:2])
        output = self.engine.update(boxes, image)
        for track in self.engine.tracked_stracks + self.engine.lost_stracks:
            if track.frame_id == self.engine.frame_id:
                self.last_seen[track.track_id] = now
        # Los buffers externos también quedan acotados en escenas densas.
        self.engine.tracked_stracks = self.engine.tracked_stracks[: self.max_tracks]
        room = max(0, self.max_tracks - len(self.engine.tracked_stracks))
        self.engine.lost_stracks = sorted(self.engine.lost_stracks, key=lambda t: t.frame_id, reverse=True)[:room]
        self.engine.removed_stracks = self.engine.removed_stracks[-self.max_tracks :]
        keep_ids = {track.track_id for track in self.engine.tracked_stracks + self.engine.lost_stracks}
        self.last_seen = {key: value for key, value in self.last_seen.items() if key in keep_ids}
        return [
            TrackedPerson(int(row[4]), tuple(float(v) for v in row[:4]), float(row[5]))
            for row in output
            if int(row[4]) in keep_ids and int(row[6]) == 0
        ]
