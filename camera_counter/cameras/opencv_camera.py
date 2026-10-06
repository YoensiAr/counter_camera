"""USB, archivos y RTSP con OpenCV, sin revelar URLs con credenciales."""

import sys
import time
from datetime import datetime, timedelta, timezone

import cv2

from camera_counter.cameras.base import BaseCamera, CameraError
from camera_counter.config import Config
from camera_counter.types import FramePacket


class OpenCVCamera(BaseCamera):
    def __init__(self, config: Config, kind: str = "opencv"):
        self.config = config
        self.kind = kind
        source = config.camera.source
        self.finite = kind == "video" or (isinstance(source, str) and "://" not in source and not source.isdecimal())
        self.lossless = self.finite
        self.capture = None
        self.sequence = 0
        self.fps = config.camera.fps

    def open(self) -> None:
        source = self.config.camera.source
        if self.finite:
            source = str(self.config.path(str(source)))
        elif isinstance(source, str) and source.isdecimal():
            source = int(source)
        if isinstance(source, str) and "://" in source:
            timeout = int(self.config.camera.read_timeout_seconds * 1000)
            self.capture = cv2.VideoCapture(
                source,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    timeout,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    timeout,
                ],
            )
        else:
            backend = cv2.CAP_DSHOW if sys.platform == "win32" and isinstance(source, int) else cv2.CAP_ANY
            self.capture = cv2.VideoCapture(source, backend)
            if not self.capture.isOpened() and backend != cv2.CAP_ANY:
                self.capture.release()
                self.capture = cv2.VideoCapture(source)
        if not self.capture.isOpened():
            self.close()
            raise CameraError("No se pudo abrir la cámara o el video. Revisa el índice, la ruta y los permisos.")
        if not self.finite:
            for prop, value in [
                (cv2.CAP_PROP_FRAME_WIDTH, self.config.camera.width),
                (cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera.height),
                (cv2.CAP_PROP_FPS, self.config.camera.fps),
                (cv2.CAP_PROP_BUFFERSIZE, 1),
            ]:
                self.capture.set(prop, value)
        else:
            reported = self.capture.get(cv2.CAP_PROP_FPS)
            self.fps = reported if 0 < reported < 500 else self.config.camera.fps
        self.sequence = 0
        self.started = time.monotonic()
        self.started_utc = datetime.now(timezone.utc)
        self.status = "conectada"

    def read(self) -> FramePacket | None:
        success, frame = self.capture.read()
        if not success:
            if self.finite:
                self.status = "video finalizado"
                return None
            self.status = "desconectada"
            raise CameraError("Se perdió la señal de la cámara.")
        now = time.monotonic()
        timeline = self.sequence / self.fps if self.finite else now
        timestamp = self.started_utc + timedelta(seconds=timeline) if self.finite else datetime.now(timezone.utc)
        packet = FramePacket(frame, self.sequence, now, timestamp, timeline)
        self.sequence += 1
        return packet

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        if self.status != "video finalizado":
            self.status = "detenida"
