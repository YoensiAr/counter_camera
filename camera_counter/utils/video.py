"""Anotación de video y grabación opcional con segmentos y límites de disco."""

import logging
import time
import unicodedata
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

log = logging.getLogger(__name__)


def annotate(image, people, counter, stats, fps, camera_status, identities=None):
    image = image.copy()
    height, width = image.shape[:2]
    if counter.config.roi is not None:
        x1, y1, x2, y2 = (int(v * size) for v, size in zip(counter.config.roi, (width, height, width, height)))
        outside = (image.astype(np.float32) * .55).astype(np.uint8)
        outside[y1:y2, x1:x2] = image[y1:y2, x1:x2]
        image = outside
        cv2.rectangle(image, (x1, y1), (x2, y2), (220, 205, 115), 2)
    line = counter.line
    a, b = tuple(map(int, line.a)), tuple(map(int, line.b))
    normal = np.array(line.normal)
    margin = normal * line.margin
    polygon = np.array(
        [np.array(a) + margin, np.array(b) + margin, np.array(b) - margin, np.array(a) - margin], np.int32
    )
    tint = image.copy()
    cv2.fillPoly(tint, [polygon], (100, 130, 65))
    image = cv2.addWeighted(image, 0.78, tint, 0.22, 0)
    cv2.line(image, a, b, (155, 231, 194), 2, cv2.LINE_AA)
    middle = (np.array(a) + np.array(b)) / 2
    direction = 1 if counter.config.entry_to == "positive" else -1
    arrow_start = tuple((middle - normal * direction * 30).astype(int))
    arrow_end = tuple((middle + normal * direction * 42).astype(int))
    cv2.arrowedLine(image, arrow_start, arrow_end, (155, 231, 194), 2, tipLength=0.25)
    cv2.putText(
        image,
        "ENTRADA",
        (arrow_end[0] + 8, arrow_end[1]),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        (195, 255, 220),
        1,
        cv2.LINE_AA,
    )
    for person in people:
        x1, y1, x2, y2 = map(int, person.box)
        color = (200, 200, 100) if person.observed else (135, 140, 150)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        anchor = tuple(int(v) for v in counter.anchor(person))
        cv2.circle(image, anchor, 4, (130, 230, 240), -1)
        label = f"ID {person.track_id}  {person.confidence:.0%}" + (" ~" if not person.observed else "")
        if identities and person.track_id in identities:
            label += " | " + identities[person.track_id]
        cv2.putText(image, label, (max(0, x1), max(58, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.43, color, 1, cv2.LINE_AA)
        memory = counter.tracks.get(person.track_id)
        if memory and len(memory.history) > 1:
            points = np.array(memory.history, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(image, [points], False, color, 1, cv2.LINE_AA)
    cv2.rectangle(image, (0, 0), (width, 46), (29, 31, 30), -1)
    text = (
        f"Unicos {stats.get('unique_visitors_today', 0)}    Entradas {stats['counted_entries_today']}"
        f"    Salidas {stats['counted_exits_today']}    Dentro {stats['occupancy']}"
    )
    cv2.putText(image, text, (12, 20), cv2.FONT_HERSHEY_SIMPLEX, min(0.5, width / 950), (235, 241, 235), 1, cv2.LINE_AA)
    safe_status = unicodedata.normalize("NFKD", camera_status).encode("ascii", "ignore").decode()
    cv2.putText(
        image,
        f"{fps:.1f} FPS | {safe_status}",
        (12, 37),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.37,
        (164, 180, 172),
        1,
        cv2.LINE_AA,
    )
    return image


class Recorder:
    def __init__(self, config):
        self.config = config
        self.writer = None
        self.file = None
        self.previous = None
        self.written = 0
        self.error = ""
        self.last_cleanup = 0.0

    def _start(self, image, timeline):
        directory = self.config.path(self.config.recording.directory)
        directory.mkdir(parents=True, exist_ok=True)
        filename = (
            "counter_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8] + ".mp4"
        )
        self.file = directory / filename
        height, width = image.shape[:2]
        self.writer = cv2.VideoWriter(
            str(self.file), cv2.VideoWriter_fourcc(*"mp4v"), self.config.camera.fps, (width, height)
        )
        if not self.writer.isOpened():
            self.close()
            raise RuntimeError("No se pudo abrir el codificador MP4; revisa OpenCV y permisos de la carpeta.")
        self.segment_start = timeline
        self.written = 0
        self.previous = image
        self.shape = image.shape
        self.cleanup()

    def write(self, image, timeline):
        if not self.config.recording.enabled:
            self.close()
            return
        try:
            if self.writer is not None and (
                image.shape != self.shape
                or timeline - self.segment_start >= self.config.recording.segment_seconds
                or timeline < self.segment_start
            ):
                self.close()
            if self.writer is None:
                self._start(image, timeline)
            due = round((timeline - self.segment_start) * self.config.camera.fps) + 1
            if due - self.written > self.config.camera.fps * 2:
                self.close()
                self._start(image, timeline)
                due = 1
            while self.written < due:
                self.writer.write(image if self.written == due - 1 else self.previous)
                self.written += 1
            self.previous = image
            if time.monotonic() - self.last_cleanup > 5:
                self.cleanup()
                limit = self.config.recording.max_total_mb * 1024 * 1024
                if self.file.stat().st_size > limit / 2:
                    self.close()
        except (OSError, RuntimeError, cv2.error) as exc:
            self.error = str(exc)
            self.config.recording.enabled = False
            self.close()
            log.error("Grabación desactivada: %s", self.error)

    def cleanup(self):
        self.last_cleanup = time.monotonic()
        directory = self.config.path(self.config.recording.directory)
        files = sorted(directory.glob("counter_*.mp4"), key=lambda path: path.stat().st_mtime)
        cutoff = time.time() - self.config.recording.retention_days * 86400
        limit = self.config.recording.max_total_mb * 1024 * 1024
        total = sum(path.stat().st_size for path in files)
        for path in files:
            if path == self.file:
                continue
            size = path.stat().st_size
            if path.stat().st_mtime < cutoff or total > limit:
                path.unlink()
                total -= size

    def close(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        self.previous = None
