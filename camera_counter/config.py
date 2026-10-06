"""Configuración validada; las rutas relativas parten del archivo YAML."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


@dataclass
class CameraConfig:
    type: str = "auto"
    source: int | str = 0
    name: str = "entrada_principal"
    width: int = 640
    height: int = 480
    fps: float = 20.0
    realtime: bool = True
    queue_size: int = 2
    reconnect_seconds: float = 2.0
    read_timeout_seconds: float = 5.0
    imx500_model: str = ""
    imx500_person_class: int = 0
    imx500_bbox_order: str = "xy"
    imx500_boxes_normalized: bool = False
    imx500_preserve_aspect_ratio: bool = True
    imx500_tensor_timeout_seconds: float = 15.0
    allow_cpu_fallback: bool = True


@dataclass
class DetectionConfig:
    model: str = "auto"
    device: str = "auto"
    confidence: float = 0.10
    iou: float = 0.5
    image_size: int = 320
    inference_stride: int = 1
    max_detections: int = 100
    optical_flow_preview: bool = True
    cpu_threads: int = 2


@dataclass
class TrackingConfig:
    type: str = "bytetrack"
    high_threshold: float = 0.35
    low_threshold: float = 0.10
    new_threshold: float = 0.40
    match_threshold: float = 0.80
    max_lost_seconds: float = 2.5
    max_tracks: int = 512


@dataclass
class LineConfig:
    p1: list[float] = field(default_factory=lambda: [0.1, 0.5])
    p2: list[float] = field(default_factory=lambda: [0.9, 0.5])
    entry_to: str = "positive"
    margin_px: float = 12.0
    confirmation_frames: int = 3
    cooldown_seconds: float = 1.0
    history_size: int = 32
    anchor: str = "center"
    roi: list[float] | None = None

    def validate(self) -> None:
        if not isinstance(self.anchor, str) or self.anchor not in {"center", "feet", "head"}:
            raise ValueError("line.anchor debe ser center, feet o head.")
        for point in (self.p1, self.p2):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("Cada punto de la línea debe contener dos coordenadas.")
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1
                for v in point
            ):
                raise ValueError("Las coordenadas deben estar entre 0 y 1.")
        if math.dist(self.p1, self.p2) < 0.01:
            raise ValueError("Los extremos de la línea deben estar separados.")
        if self.entry_to not in {"positive", "negative"}:
            raise ValueError("entry_to debe ser positive o negative.")
        _number(self.margin_px, 0, 500, "line.margin_px")
        _number(self.cooldown_seconds, 0, 3600, "line.cooldown_seconds")
        _integer(self.confirmation_frames, 2, 60, "line.confirmation_frames")
        _integer(self.history_size, self.confirmation_frames * 2, 512, "line.history_size")
        if self.roi is not None:
            if not isinstance(self.roi, (list, tuple)) or len(self.roi) != 4:
                raise ValueError("La zona de acceso requiere [x1,y1,x2,y2].")
            for value in self.roi:
                _number(value, 0, 1, "line.roi")
            x1, y1, x2, y2 = self.roi
            if x2 - x1 < .02 or y2 - y1 < .02:
                raise ValueError("La zona de acceso debe tener ancho y alto suficientes.")
            lower, upper = 0.0, 1.0
            for origin, target, minimum, maximum in ((self.p1[0], self.p2[0], x1, x2), (self.p1[1], self.p2[1], y1, y2)):
                delta = target - origin
                if abs(delta) < 1e-12:
                    if not minimum <= origin <= maximum:
                        raise ValueError("La línea debe atravesar la zona de acceso.")
                else:
                    a, b = sorted(((minimum - origin) / delta, (maximum - origin) / delta))
                    lower, upper = max(lower, a), min(upper, b)
            if lower >= upper:
                raise ValueError("La línea debe atravesar la zona de acceso.")


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    max_stream_clients: int = 3


@dataclass
class StorageConfig:
    database: str = "data/counter.sqlite3"
    retention_days: int = 90
    timezone: str = "America/Santo_Domingo"
    log_directory: str = "logs"


@dataclass
class RecordingConfig:
    enabled: bool = False
    directory: str = "recordings"
    segment_seconds: int = 300
    retention_days: int = 7
    max_total_mb: int = 2048


@dataclass
class VisitorsConfig:
    enabled: bool = True
    mode: str = "hybrid"
    window: str = "calendar_day"
    window_hours: float = 24.0
    detector_model: str = "models/face_detection_yunet_2023mar.onnx"
    recognizer_model: str = "models/face_recognition_sface_2021dec.onnx"
    key_file: str = "data/visitors.key"
    match_threshold: float = 0.50
    new_threshold: float = 0.35
    ambiguity_margin: float = 0.08
    detection_threshold: float = 0.90
    min_face_pixels: int = 48
    min_sharpness: float = 50.0
    min_samples: int = 2
    sample_interval_seconds: float = 0.3
    sample_ttl_seconds: float = 3.0
    pending_seconds: float = 8.0
    max_identities: int = 10000
    max_faces_per_frame: int = 8
    detection_max_side: int = 640
    body_model: str = "models/osnet_x0_25_msmt17.onnx"
    body_match_threshold: float = 0.85
    body_new_threshold: float = 0.55
    body_ambiguity_margin: float = 0.08
    body_consistency_threshold: float = 0.65
    body_min_samples: int = 3
    body_max_views: int = 6
    body_min_width: int = 32
    body_min_height: int = 96
    body_min_confidence: float = 0.45
    body_min_sharpness: float = 8.0
    body_max_overlap: float = 0.30
    continuity_gap_seconds: float = 0.8
    continuity_evidence_seconds: float = 3.0
    continuity_speed: float = 3.0

    def validate(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("visitors.enabled debe ser true o false.")
        if not isinstance(self.mode, str) or self.mode not in {"hybrid", "face"}:
            raise ValueError("visitors.mode debe ser hybrid o face.")
        if not isinstance(self.window, str) or self.window not in {"calendar_day", "hours"}:
            raise ValueError("visitors.window debe ser calendar_day o hours.")
        for key, low, high in [
            ("window_hours", 1, 168),
            ("match_threshold", 0.1, 1),
            ("new_threshold", -1, 0.99),
            ("ambiguity_margin", 0, 0.5),
            ("detection_threshold", 0.5, 1),
            ("min_sharpness", 0, 10000),
            ("sample_interval_seconds", 0.05, 5),
            ("sample_ttl_seconds", 0.1, 15),
            ("pending_seconds", 1, 60),
            ("body_match_threshold", 0.5, 1),
            ("body_new_threshold", -1, 0.99),
            ("body_ambiguity_margin", 0.01, 0.5),
            ("body_consistency_threshold", 0.1, 1),
            ("body_min_confidence", 0.1, 1),
            ("body_min_sharpness", 0, 10000),
            ("body_max_overlap", 0.05, 0.8),
            ("continuity_gap_seconds", 0.1, 3),
            ("continuity_evidence_seconds", 0.2, 10),
            ("continuity_speed", 0.5, 10),
        ]:
            _number(getattr(self, key), low, high, "visitors." + key)
        for key, low, high in [
            ("min_face_pixels", 20, 500),
            ("min_samples", 2, 5),
            ("max_identities", 1, 50000),
            ("max_faces_per_frame", 1, 32),
            ("detection_max_side", 320, 1920),
            ("body_min_samples", 2, 8),
            ("body_max_views", 2, 12),
            ("body_min_width", 16, 500),
            ("body_min_height", 32, 1000),
        ]:
            _integer(getattr(self, key), low, high, "visitors." + key)
        if self.new_threshold >= self.match_threshold:
            raise ValueError("visitors.new_threshold debe ser menor que match_threshold.")
        if self.body_new_threshold >= self.body_match_threshold:
            raise ValueError("body_new_threshold debe ser menor que body_match_threshold.")
        if self.continuity_evidence_seconds < self.continuity_gap_seconds:
            raise ValueError("continuity_evidence_seconds debe cubrir continuity_gap_seconds.")
        if self.sample_ttl_seconds < self.sample_interval_seconds * (self.min_samples - 1):
            raise ValueError("sample_ttl_seconds no permite reunir min_samples.")
        if self.sample_ttl_seconds < self.sample_interval_seconds * (self.body_min_samples - 1):
            raise ValueError("sample_ttl_seconds no permite reunir body_min_samples.")
        for key in ("detector_model", "recognizer_model", "key_file", "body_model"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ValueError("visitors." + key + " debe ser una ruta.")


def _number(value: Any, low: float, high: float, key: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"{key} debe estar entre {low} y {high}.")


def _integer(value: Any, low: int, high: int, key: str) -> None:
    _number(value, low, high, key)
    if not isinstance(value, int):
        raise ValueError(f"{key} debe ser entero.")


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    line: LineConfig = field(default_factory=LineConfig)
    web: WebConfig = field(default_factory=WebConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    visitors: VisitorsConfig = field(default_factory=VisitorsConfig)
    gui: bool = False
    base_dir: Path = field(default_factory=Path.cwd, repr=False)
    config_path: Path | None = field(default=None, repr=False)

    def path(self, value: str) -> Path:
        result = Path(value).expanduser()
        return result if result.is_absolute() else self.base_dir / result

    def validate(self) -> None:
        self.line.validate()
        self.visitors.validate()
        if self.camera.type not in {"auto", "usb", "opencv", "rtsp", "video", "csi", "picamera2", "imx500", "mock", "browser"}:
            raise ValueError("Tipo de cámara desconocido.")
        if self.tracking.type not in {"bytetrack", "botsort"}:
            raise ValueError("El tracker debe ser bytetrack o botsort.")
        if self.camera.imx500_bbox_order not in {"xy", "yx"}:
            raise ValueError("imx500_bbox_order debe ser xy o yx.")
        if not isinstance(self.camera.source, (int, str)) or isinstance(self.camera.source, bool):
            raise ValueError("camera.source debe ser un índice, ruta o URL.")
        if not isinstance(self.camera.name, str) or not self.camera.name.strip():
            raise ValueError("La cámara necesita un nombre.")
        for key, value, lo, hi in [
            ("camera.width", self.camera.width, 64, 7680),
            ("camera.height", self.camera.height, 64, 4320),
            ("camera.queue_size", self.camera.queue_size, 1, 8),
            ("detection.image_size", self.detection.image_size, 64, 1280),
            ("detection.inference_stride", self.detection.inference_stride, 1, 30),
            ("detection.max_detections", self.detection.max_detections, 1, 512),
            ("detection.cpu_threads", self.detection.cpu_threads, 1, 64),
            ("tracking.max_tracks", self.tracking.max_tracks, 1, 4096),
            ("web.port", self.web.port, 1, 65535),
            ("web.max_stream_clients", self.web.max_stream_clients, 1, 16),
            ("storage.retention_days", self.storage.retention_days, 1, 3650),
            ("recording.segment_seconds", self.recording.segment_seconds, 5, 3600),
            ("recording.retention_days", self.recording.retention_days, 1, 365),
            ("recording.max_total_mb", self.recording.max_total_mb, 10, 1000000),
        ]:
            _integer(value, lo, hi, key)
        for key, value, lo, hi in [
            ("camera.fps", self.camera.fps, 1, 120),
            ("camera.reconnect_seconds", self.camera.reconnect_seconds, 0.1, 60),
            ("camera.read_timeout_seconds", self.camera.read_timeout_seconds, 0.5, 30),
            ("camera.imx500_tensor_timeout_seconds", self.camera.imx500_tensor_timeout_seconds, 1, 300),
            ("tracking.max_lost_seconds", self.tracking.max_lost_seconds, 0.1, 60),
            ("tracking.low_threshold", self.tracking.low_threshold, 0, 1),
            ("tracking.high_threshold", self.tracking.high_threshold, 0, 1),
            ("tracking.new_threshold", self.tracking.new_threshold, 0, 1),
            ("tracking.match_threshold", self.tracking.match_threshold, 0, 1),
            ("detection.confidence", self.detection.confidence, 0.001, 1),
            ("detection.iou", self.detection.iou, 0.01, 1),
        ]:
            _number(value, lo, hi, key)
        if not self.tracking.low_threshold <= self.tracking.high_threshold <= self.tracking.new_threshold:
            raise ValueError("Se requiere low_threshold <= high_threshold <= new_threshold.")
        if self.detection.confidence > self.tracking.high_threshold:
            raise ValueError("confidence no debe superar high_threshold del tracker.")
        if self.detection.image_size % 32:
            raise ValueError("image_size debe ser múltiplo de 32.")
        for section in (self.camera, self.detection, self.web, self.recording):
            for f in fields(section):
                if f.type == "bool" and not isinstance(getattr(section, f.name), bool):
                    raise ValueError(f"{f.name} debe ser true o false.")
        if not isinstance(self.gui, bool):
            raise ValueError("gui debe ser true o false.")
        try:
            ZoneInfo(self.storage.timezone)
        except (ZoneInfoNotFoundError, TypeError) as exc:
            raise ValueError("Zona horaria inválida; instala tzdata en Windows.") from exc

    def save_line(self, line: LineConfig) -> None:
        """Actualiza únicamente la línea, sin persistir secretos ni overrides CLI."""
        line.validate()
        self._save_section("line", asdict(line))
        self.line = line

    def save_visitors(self, visitors: VisitorsConfig) -> None:
        visitors.validate()
        self._save_section("visitors", asdict(visitors))
        self.visitors = visitors

    def _save_section(self, section: str, value: dict) -> None:
        target = self.config_path or self.base_dir / "config.yaml"
        data = yaml.safe_load(target.read_text(encoding="utf-8")) if target.exists() else {}
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("El YAML debe ser un mapa.")
        data[section] = value
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        temporary.replace(target)
        self.config_path = target


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    target = Path(path).resolve() if path else Path("config.yaml").resolve()
    if path and not target.is_file():
        raise ValueError(f"No existe el archivo de configuración: {target.name}")
    if target.exists():
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("La configuración debe ser un mapa YAML.")
        allowed = {f.name for f in fields(Config)} - {"base_dir", "config_path"}
        if set(data) - allowed:
            raise ValueError(f"Opciones desconocidas: {sorted(set(data) - allowed)}")
        for name, value in data.items():
            if name == "gui":
                cfg.gui = value
                continue
            if not isinstance(value, dict):
                raise ValueError(f"{name} debe ser un mapa.")
            kind = type(getattr(cfg, name))
            try:
                setattr(cfg, name, kind(**value))
            except TypeError as exc:
                raise ValueError(f"Opción desconocida en {name}.") from exc
        cfg.base_dir = target.parent
        cfg.config_path = target
    if "CAMERA_COUNTER_SOURCE" in os.environ:
        source = os.environ["CAMERA_COUNTER_SOURCE"]
        cfg.camera.source = int(source) if source.isdecimal() else source
    if "CAMERA_COUNTER_HOST" in os.environ:
        cfg.web.host = os.environ["CAMERA_COUNTER_HOST"]
    if "CAMERA_COUNTER_PORT" in os.environ:
        cfg.web.port = int(os.environ["CAMERA_COUNTER_PORT"])
    cfg.validate()
    return cfg
