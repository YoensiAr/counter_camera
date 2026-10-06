"""Productor con cola acotada: los archivos conservan todos sus fotogramas."""

import logging
import queue
import threading
import time

from camera_counter.cameras.base import BaseCamera
from camera_counter.config import Config

log = logging.getLogger(__name__)


class CaptureWorker:
    def __init__(self, camera: BaseCamera, config: Config):
        self.camera, self.config = camera, config
        self.queue = queue.Queue(maxsize=config.camera.queue_size)
        self.stop_event, self.done = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run, name="captura", daemon=True)
        self.dropped = 0
        self.status = "iniciando cámara"
        self.error = ""

    def start(self):
        self.thread.start()

    def _publish(self, packet):
        while not self.stop_event.is_set():
            try:
                self.queue.put(packet, timeout=0.1 if self.camera.lossless else 0)
                return
            except queue.Full:
                if self.camera.lossless:
                    continue
                try:
                    removed = self.queue.get_nowait()
                    packet.discontinuity |= removed.discontinuity
                    self.dropped += 1
                except queue.Empty:
                    pass

    def _run(self):
        discontinuity = False
        try:
            while not self.stop_event.is_set():
                try:
                    self.camera.open()
                    self.status, self.error = self.camera.status, ""
                    next_due = time.monotonic()
                    while not self.stop_event.is_set():
                        packet = self.camera.read()
                        self.status = self.camera.status
                        if hasattr(self.camera, "dropped"):
                            self.dropped = max(self.dropped, int(self.camera.dropped))
                        if packet is None:
                            self.status = "video finalizado"
                            return
                        packet.discontinuity |= discontinuity
                        discontinuity = False
                        self._publish(packet)
                        if self.config.camera.realtime and self.camera.lossless:
                            next_due += 1 / self.camera.fps
                            self.stop_event.wait(max(0, next_due - time.monotonic()))
                except Exception as exc:
                    self.error = str(exc)
                    self.status = "sin señal; reintentando"
                    log.error("Captura: %s", self.error)
                    if self.camera.finite:
                        return
                    discontinuity = True
                finally:
                    try:
                        self.camera.close()
                    except Exception:
                        log.error("La cámara no pudo completar el cierre del controlador.")
                self.stop_event.wait(self.config.camera.reconnect_seconds)
        finally:
            self.done.set()

    def stop(self):
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=self.config.camera.read_timeout_seconds + 1)
            if self.thread.is_alive():
                log.error("El controlador de cámara no respondió al cierre; el proceso liberará sus recursos al salir.")
