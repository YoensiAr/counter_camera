"""Una sola solicitud por imagen y metadatos; imports exclusivos dentro de open."""

import logging
import time
from datetime import datetime, timezone

from camera_counter.cameras.base import BaseCamera, CameraError
from camera_counter.config import Config
from camera_counter.types import FramePacket


class Picamera2Camera(BaseCamera):
    def __init__(self, config: Config):
        self.config = config
        self.picam = None
        self.sequence = 0
        self.fps = config.camera.fps

    def open(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CameraError("Instala python3-picamera2 con apt y usa un venv con --system-site-packages.") from exc
        try:
            self.picam = Picamera2(int(self.config.camera.source))
            self._start()
        except Exception as exc:
            self.close()
            raise CameraError(f"No se pudo iniciar Picamera2 ({type(exc).__name__}).") from exc

    def _start(self) -> None:
        cfg = self.config.camera
        # RGB888 en libcamera entrega bytes BGR, directamente compatibles con OpenCV.
        video = self.picam.create_video_configuration(
            main={"size": (cfg.width, cfg.height), "format": "RGB888"},
            controls={"FrameRate": cfg.fps},
            buffer_count=4,
        )
        self.picam.configure(video)
        self.picam.start()
        self.sequence = 0
        self.status = "conectada"

    def _packet(self, image, metadata) -> FramePacket:
        now = time.monotonic()
        return FramePacket(image, self.sequence, now, datetime.now(timezone.utc), now)

    def read(self) -> FramePacket:
        try:
            job = self.picam.capture_request(wait=False)
            request = self.picam.wait(job, timeout=self.config.camera.read_timeout_seconds)
            try:
                packet = self._packet(request.make_array("main").copy(), request.get_metadata())
            finally:
                request.release()
            self.sequence += 1
            return packet
        except Exception as exc:
            raise CameraError(f"Fallo de captura Picamera2 ({type(exc).__name__}).") from exc

    def close(self) -> None:
        if self.picam is not None:
            try:
                self.picam.stop()
            except Exception:
                logging.getLogger(__name__).debug("La cámara ya estaba detenida o no llegó a iniciar.")
            finally:
                try:
                    self.picam.close()
                finally:
                    self.picam = None
        self.status = "detenida"
