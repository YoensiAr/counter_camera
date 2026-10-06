"""Cámara remota alimentada por fotogramas JPEG enviados desde un navegador."""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np

from camera_counter.cameras.base import BaseCamera, CameraError
from camera_counter.config import Config
from camera_counter.types import FramePacket


class BrowserCamera(BaseCamera):
    """Adaptador de cámara para despliegues cloud.

    El navegador captura la cámara con getUserMedia() y publica JPEGs a la API.
    El resto de la aplicación recibe FramePacket normales, igual que con USB/CSI.
    """

    finite = False
    lossless = False
    model_status = "YOLO en servidor"

    def __init__(self, config: Config):
        self.config = config
        self.fps = float(config.camera.fps)
        self.status = "esperando cámara del navegador"
        self._queue: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=config.camera.queue_size)
        self._closed = threading.Event()
        self._sequence = 0
        self._last_received = 0.0
        self._last_delivered = 0.0
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def last_received_seconds_ago(self) -> float | None:
        if not self._last_received:
            return None
        return max(0.0, time.monotonic() - self._last_received)

    def open(self) -> None:
        self._closed.clear()
        self.status = "esperando cámara del navegador"

    def submit_jpeg(self, data: bytes) -> None:
        if self._closed.is_set():
            raise CameraError("La cámara del navegador está detenida.")
        if not data:
            raise CameraError("Se recibió un fotograma vacío.")
        if len(data) > 2_500_000:
            raise CameraError("El fotograma supera 2.5 MB.")

        now = time.monotonic()
        self._last_received = now
        self.status = "cámara web conectada"
        item = (data, now)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._dropped += 1
            except queue.Empty:
                pass
            self._queue.put_nowait(item)

    def read(self) -> FramePacket | None:
        while not self._closed.is_set():
            try:
                data, received_at = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._last_received and time.monotonic() - self._last_received > 2.5:
                    self.status = "cámara web sin señal"
                else:
                    self.status = "esperando cámara del navegador"
                continue

            array = np.frombuffer(data, dtype=np.uint8)
            image = cv2.imdecode(array, cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                raise CameraError("No se pudo decodificar el JPEG recibido del navegador.")

            target_w, target_h = int(self.config.camera.width), int(self.config.camera.height)
            height, width = image.shape[:2]
            if (width, height) != (target_w, target_h):
                image = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)

            now = time.monotonic()
            gap = now - self._last_delivered if self._last_delivered else 0.0
            self._last_delivered = now
            self._sequence += 1
            self.status = "cámara web conectada"
            return FramePacket(
                image=image,
                sequence=self._sequence,
                captured_at=received_at,
                timestamp=datetime.now(timezone.utc),
                timeline=now,
                discontinuity=bool(gap > max(3.0, self.config.tracking.max_lost_seconds * 1.5)),
            )
        return None

    def close(self) -> None:
        self._closed.set()
        self.status = "cámara web detenida"
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
