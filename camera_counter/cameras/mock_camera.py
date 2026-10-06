"""Personas sintéticas como cajas, sin IDs: el tracker debe asociarlas."""

import time
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from camera_counter.cameras.base import BaseCamera
from camera_counter.config import Config
from camera_counter.types import Detection, FramePacket


class MockCamera(BaseCamera):
    lossless = True
    model_status = "Simulación: detecciones sintéticas"

    def __init__(self, config: Config, frames: int | None = None):
        self.config = config
        self.frames = frames
        self.finite = frames is not None
        self.sequence = 0
        self.fps = config.camera.fps

    def open(self) -> None:
        self.sequence = 0
        self.started = datetime.now(timezone.utc)
        self.status = "simulación activa"

    def read(self) -> FramePacket | None:
        if self.frames is not None and self.sequence >= self.frames:
            return None
        width, height = self.config.camera.width, self.config.camera.height
        image = np.full((height, width, 3), (31, 27, 21), np.uint8)
        for x in range(0, width, 40):
            cv2.line(image, (x, 0), (x, height), (43, 38, 30), 1)
        for y in range(0, height, 40):
            cv2.line(image, (0, y), (width, y), (43, 38, 30), 1)
        cycle = self.sequence % 320
        positions = []
        if cycle < 220:
            y = 0.16 + 0.66 * min(cycle / 80, 1)
            if cycle > 120:
                y = 0.82 - 0.66 * min((cycle - 120) / 80, 1)
            if cycle not in range(55, 61):
                positions.append((0.34, y, (190, 173, 85)))
        if 25 <= cycle < 240:
            positions.append((0.67, 0.16 + 0.66 * min((cycle - 25) / 95, 1), (114, 192, 166)))
        detections = []
        for x, y, color in positions:
            cx, cy = x * width, y * height
            box = (cx - width * 0.043, cy - height * 0.09, cx + width * 0.043, cy + height * 0.09)
            detections.append(Detection(box, 0.93))
            cv2.rectangle(image, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), color, -1)
            cv2.circle(image, (int(cx), int(box[1] - 12)), 10, color, -1)
        cv2.putText(
            image,
            "SIMULACION / SIN CAMARA",
            (18, height - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (150, 170, 180),
            1,
            cv2.LINE_AA,
        )
        timeline = self.sequence / self.fps
        packet = FramePacket(
            image, self.sequence, time.monotonic(), self.started + timedelta(seconds=timeline), timeline, detections
        )
        self.sequence += 1
        return packet

    def close(self) -> None:
        self.status = "detenida"
