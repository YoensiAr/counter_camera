"""Orquestación: la captura, inferencia, conteo y web comparten una sola sesión."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone

import cv2
import psutil

from camera_counter.cameras import make_camera
from camera_counter.cameras.capture import CaptureWorker
from camera_counter.config import Config, LineConfig, VisitorsConfig
from camera_counter.counting.line_counter import LineCounter
from camera_counter.database.repository import Repository
from camera_counter.detection.detector import YOLODetector
from camera_counter.detection.flow import FlowPreview
from camera_counter.detection.tracker import PersonTracker
from camera_counter.utils.video import Recorder, annotate
from camera_counter.visitors.service_hybrid import HybridVisitorService as VisitorService

log = logging.getLogger(__name__)


class CounterApplication:
    def __init__(self, config: Config, *, camera=None, repository=None):
        config.validate()
        self.config = config
        self.camera = camera or make_camera(config)
        self.repository = repository or Repository(config.path(config.storage.database), config.storage.timezone)
        self.capture = CaptureWorker(self.camera, config)
        self.counter = LineCounter(
            config.line,
            config.camera.width,
            config.camera.height,
            config.tracking.max_lost_seconds,
            config.tracking.max_tracks,
        )
        self.tracker = None
        self.detector = None
        self.flow = FlowPreview()
        self.recorder = Recorder(config)
        self.lock = threading.RLock()
        self.frames_condition = threading.Condition()
        self.stream_clients = 0
        self.latest_jpeg = None
        self.jpeg_sequence = 0
        self.stop_event = threading.Event()
        self.running = False
        self.closed = False
        self.session = self.repository.start_session(config.camera.name)
        self.visitors = VisitorService(config, self.repository)
        self.metrics = {
            "fps": 0.0,
            "inference_fps": 0.0,
            "latency_ms": 0.0,
            "memory_mb": 0.0,
            "processed_frames": 0,
            "visible_tracks": 0,
            "model": "iniciando",
            "error": "",
        }
        self.server = None
        self.web_thread = None
        self.last_stats = self.repository.stats()
        self.last_refresh = 0.0

    def snapshot(self) -> dict:
        with self.lock:
            result = dict(self.metrics)
            result.update(self.repository.stats())
            result.update(
                {
                    "running": self.running,
                    "camera": self.camera.status if self.config.camera.type == "browser" else self.capture.status,
                    "camera_name": self.config.camera.name,
                    "camera_error": self.capture.error,
                    "tracker": self.config.tracking.type,
                    "recording": self.config.recording.enabled,
                    "recording_error": self.recorder.error,
                    "dropped_frames": self.capture.dropped,
                    "line": asdict(self.config.line),
                    "session": self.session,
                    "width": self.counter.width,
                    "height": self.counter.height,
                    "simulated": self.config.camera.type == "mock",
                    "browser_camera": self.config.camera.type == "browser",
                    "visitors": self.visitors.status(),
                }
            )
        return result

    def change_line(self, payload: dict) -> dict:
        with self.lock:
            data = asdict(self.config.line)
            allowed = {"p1", "p2", "entry_to", "margin_px", "confirmation_frames", "cooldown_seconds", "anchor", "roi"}
            if set(payload) - allowed:
                raise ValueError("El formulario contiene opciones desconocidas.")
            data.update(payload)
            line = LineConfig(**data)
            line.validate()
            self.config.save_line(line)
            if any(getattr(line, key) != getattr(self.counter.config, key) for key in ("p1", "p2", "entry_to", "anchor", "roi")):
                totals = self.repository.stats()
                if totals["entries"] or totals["exits"]:
                    self.repository.mark_occupancy_uncertain("counting_boundary_changed")
            self.counter.reconfigure(line, self.counter.width, self.counter.height)
        return asdict(line)

    def reset_counters(self):
        with self.lock:
            self.repository.reset_counters()
            self.last_stats = self.repository.stats()

    def change_visitors(self, payload: dict) -> dict:
        with self.lock:
            allowed = {"enabled", "window", "window_hours"}
            if set(payload) - allowed:
                raise ValueError("El formulario contiene opciones desconocidas.")
            data = asdict(self.config.visitors)
            data.update(payload)
            settings = VisitorsConfig(**data)
            settings.validate()
            # Verificar modelos antes de persistir una activación.
            if settings.enabled and self.config.camera.type != "mock":
                self.visitors._load()
            self.config.save_visitors(settings)
            self.visitors.reconfigure(settings)
            return self.visitors.status()

    def forget_visitors(self):
        with self.lock:
            self.visitors.forget()

    def set_recording(self, enabled: bool):
        with self.lock:
            self.config.recording.enabled = enabled
            self.recorder.error = ""
            if not enabled:
                self.recorder.close()

    def submit_browser_frame(self, data: bytes) -> None:
        if self.config.camera.type != "browser" or not hasattr(self.camera, "submit_jpeg"):
            raise ValueError("Este servidor no está configurado para cámara del navegador.")
        self.camera.submit_jpeg(data)

    def stream(self):
        last = -1
        with self.frames_condition:
            self.stream_clients += 1
            self.frames_condition.notify_all()
        try:
            while not self.closed:
                with self.frames_condition:
                    self.frames_condition.wait_for(
                        lambda: self.closed or (self.latest_jpeg is not None and self.jpeg_sequence != last),
                        timeout=2,
                    )
                    if self.closed:
                        return
                    if self.latest_jpeg is None or self.jpeg_sequence == last:
                        continue
                    jpeg, last = self.latest_jpeg, self.jpeg_sequence
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode()
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
        finally:
            with self.frames_condition:
                self.stream_clients -= 1
                self.frames_condition.notify_all()

    def _new_session(self):
        self.repository.mark_occupancy_uncertain("camera_discontinuity")
        self.visitors.finish("camera_discontinuity")
        self.repository.end_session(self.session)
        self.session = self.repository.start_session(self.config.camera.name)
        self.tracker = PersonTracker(self.config)
        self.counter.tracks.clear()
        self.flow = FlowPreview()
        log.info("Nueva sesión de seguimiento después de una discontinuidad de cámara.")

    def _check_continuity(self):
        uncertain = self.counter.invalidate(self.visitors.take_invalidated_tracks())
        if uncertain or self.counter.lost_inside:
            self.repository.mark_occupancy_uncertain("tracking_interrupted_inside")
        self.counter.lost_inside.clear()

    def _start_web(self):
        from waitress import create_server
        from camera_counter.web.routes import create_app

        app = create_app(self)
        self.server = create_server(
            app,
            host=self.config.web.host,
            port=self.config.web.port,
            threads=self.config.web.max_stream_clients + 5,
            channel_timeout=30,
            clear_untrusted_proxy_headers=True,
        )
        self.web_thread = threading.Thread(target=self.server.run, name="panel-web", daemon=True)
        self.web_thread.start()
        host = "127.0.0.1" if self.config.web.host == "0.0.0.0" else self.config.web.host
        log.info("Panel disponible en http://%s:%d", host, self.config.web.port)

    def run(self, max_frames: int | None = None, deadline_seconds: float | None = None) -> dict:
        self.running = True
        started = window_start = time.monotonic()
        window_frames = window_inferences = 0
        total_inferences = 0
        last_packet_timeline = last_packet_clock = None
        process = psutil.Process()
        process.cpu_percent()
        try:
            # Se desactivan mensajes de OpenCV que podrían incluir credenciales RTSP.
            if hasattr(cv2, "setLogLevel"):
                cv2.setLogLevel(0)
            self.tracker = PersonTracker(self.config)
            self.visitors.start()
            if self.config.web.enabled:
                self._start_web()
            self.repository.prune(self.config.storage.retention_days)
            last_prune = time.monotonic()
            self.capture.start()
            processing_started = window_start = time.monotonic()
            while not self.stop_event.is_set():
                if deadline_seconds and time.monotonic() - started > deadline_seconds:
                    if self.metrics["processed_frames"] == 0:
                        raise RuntimeError("El diagnóstico no recibió fotogramas dentro del tiempo disponible.")
                    break
                try:
                    packet = self.capture.queue.get(timeout=0.25)
                except queue.Empty:
                    with self.lock:
                        idle_timeline = (
                            last_packet_timeline + time.monotonic() - last_packet_clock
                            if last_packet_timeline is not None
                            else time.monotonic()
                        )
                        now = datetime.now(timezone.utc)
                        self.visitors.tick(idle_timeline, now)
                        self.visitors.flush(idle_timeline, now)
                        self.counter.expire(idle_timeline)
                        self._check_continuity()
                    if self.capture.done.is_set():
                        if self.capture.error:
                            raise RuntimeError(self.capture.error)
                        break
                    continue
                with self.lock:
                    last_packet_timeline, last_packet_clock = packet.timeline, time.monotonic()
                    if packet.discontinuity:
                        self._new_session()
                    height, width = packet.image.shape[:2]
                    if (width, height) != (self.counter.width, self.counter.height):
                        self.counter.reconfigure(self.config.line, width, height)
                    number = self.metrics["processed_frames"]
                    infer = number % self.config.detection.inference_stride == 0 and not packet.inference_pending
                    if infer:
                        detections = packet.detections
                        if detections is None:
                            if self.detector is None:
                                self.detector = YOLODetector(self.config)
                            detections = self.detector.detect(packet.image)
                            self.metrics["model"] = self.detector.status
                        else:
                            self.metrics["model"] = self.camera.model_status
                        people = self.tracker.update(detections, packet.image, packet.timeline)
                        self.visitors.observe(packet.image, people, packet.timeline, packet.timestamp)
                        self._check_continuity()
                        events = self.counter.update(people, packet.timeline, packet.timestamp)
                        for event in events:
                            if self.visitors.record(event, self.session, packet.timeline):
                                log.info(
                                    "Cruce físico de %s | track %d | %s",
                                    "entrada" if event.event_type == "entry" else "salida",
                                    event.track_id,
                                    self.config.camera.name,
                                )
                        self.flow.seed(packet.image, people, packet.timeline)
                        window_inferences += 1
                        total_inferences += 1
                    else:
                        events = []
                        self.visitors.tick(packet.timeline, packet.timestamp)
                        self.counter.expire(packet.timeline)
                        people = (
                            self.flow.advance(packet.image, packet.timeline, self.config.tracking.max_lost_seconds)
                            if self.config.detection.optical_flow_preview
                            else []
                        )
                    self.visitors.flush(packet.timeline, packet.timestamp)
                    self._check_continuity()
                    window_frames += 1
                    self.metrics["processed_frames"] += 1
                    elapsed = time.monotonic() - window_start
                    if elapsed >= 0.5:
                        self.metrics["fps"] = round(window_frames / elapsed, 2)
                        self.metrics["inference_fps"] = round(window_inferences / elapsed, 2)
                        self.metrics["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
                        self.metrics["cpu_percent"] = process.cpu_percent()
                        window_start, window_frames, window_inferences = time.monotonic(), 0, 0
                    self.metrics["visible_tracks"] = sum(person.observed for person in people)
                    self.metrics["latency_ms"] = round((time.monotonic() - packet.captured_at) * 1000, 1)
                    if events or time.monotonic() - self.last_refresh >= 0.5:
                        self.last_stats = self.repository.stats()
                        self.last_refresh = time.monotonic()
                    frame = annotate(
                        packet.image, people, self.counter, self.last_stats, self.metrics["fps"], self.capture.status,
                        identities=self.visitors.track_labels(),
                    )
                    self.recorder.write(frame, packet.timeline)
                with self.frames_condition:
                    publish_video = self.stream_clients > 0 or self.latest_jpeg is None
                if publish_video:
                        success, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if success:
                            with self.frames_condition:
                                self.latest_jpeg = jpeg.tobytes()
                                self.jpeg_sequence += 1
                                self.frames_condition.notify_all()
                if self.config.gui:
                    cv2.imshow("Camera Counter - Q para salir", frame)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
                if max_frames is not None and self.metrics["processed_frames"] >= max_frames:
                    break
                if time.monotonic() - last_prune >= 3600:
                    self.repository.prune(self.config.storage.retention_days)
                    last_prune = time.monotonic()
            with self.lock:
                self.visitors.finish()
                processing_elapsed = max(time.monotonic() - processing_started, 1e-9)
                self.metrics["average_processing_fps"] = round(self.metrics["processed_frames"] / processing_elapsed, 2)
                self.metrics["average_inference_fps"] = round(total_inferences / processing_elapsed, 2)
                tail_elapsed = max(time.monotonic() - window_start, 1e-9)
                if window_frames:
                    self.metrics["fps"] = round(window_frames / tail_elapsed, 2)
                    self.metrics["inference_fps"] = round(window_inferences / tail_elapsed, 2)
                self.metrics["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
                result = self.snapshot()
                result["elapsed_seconds"] = round(time.monotonic() - started, 2)
            return result
        except Exception as exc:
            self.metrics["error"] = str(exc)
            raise
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        self.stop_event.set()
        self.running = False
        self.closed = True
        with self.frames_condition:
            self.frames_condition.notify_all()
        actions = [
            ("captura", self.capture.stop),
            ("grabación", self.recorder.close),
            ("visitantes", self.visitors.finish),
            ("caducidad facial", self.repository.purge_visitors),
        ]
        if self.server is not None:
            actions.extend(
                [
                    ("servidor", self.server.close),
                    ("peticiones web", lambda: self.server.task_dispatcher.shutdown(cancel_pending=True, timeout=3)),
                ]
            )
        if self.web_thread is not None:
            actions.append(("hilo web", lambda: self.web_thread.join(timeout=2)))
        if self.config.gui:
            actions.append(("ventana", cv2.destroyAllWindows))
        actions.extend(
            [
                ("sesión", lambda: self.repository.end_session(self.session)),
                ("SQLite", self.repository.close),
            ]
        )
        for name, action in actions:
            try:
                action()
            except Exception as exc:
                log.error("Error al cerrar %s: %s", name, exc)
