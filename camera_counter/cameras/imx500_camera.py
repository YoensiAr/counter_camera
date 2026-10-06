"""YOLO con NMS exportado a IMX500, más fallback explícito a inferencia en host."""

import logging
import time

import numpy as np

from camera_counter.cameras.base import CameraError
from camera_counter.cameras.picamera2_camera import Picamera2Camera
from camera_counter.types import Detection

log = logging.getLogger(__name__)


def decode_outputs(
    outputs,
    convert,
    input_size,
    image_size,
    *,
    order="xy",
    normalized=True,
    threshold=0.1,
    person_class=0,
    max_detections=100,
):
    """Contrato: tensores separados boxes[N,4], scores[N], classes[N], count opcional."""
    if len(outputs) < 3:
        raise ValueError("Se requieren cajas, confianzas y clases. Exporta YOLO detect con NMS.")
    boxes = np.asarray(outputs[0], dtype=np.float32).reshape(-1, 4)
    scores = np.asarray(outputs[1]).reshape(-1)
    classes = np.asarray(outputs[2]).reshape(-1)
    if len(boxes) != len(scores) or len(scores) != len(classes):
        raise ValueError("Las dimensiones de los tensores IMX500 no coinciden.")
    count = len(scores)
    if len(outputs) > 3 and np.asarray(outputs[3]).size == 1:
        count = min(count, max(0, int(np.asarray(outputs[3]).item())))
    result = []
    width, height = image_size
    for box, score, cls in zip(boxes[:count], scores[:count], classes[:count]):
        if not np.isfinite(box).all() or not np.isfinite(score) or not np.isfinite(cls):
            continue
        if score < threshold or score > 1 or not float(cls).is_integer() or int(cls) != person_class:
            continue
        xy = box[[1, 0, 3, 2]].copy() if order == "yx" else box.copy()
        if not normalized:
            xy /= np.array([input_size[0], input_size[1], input_size[0], input_size[1]])
        if np.any(np.abs(xy) > 4):
            raise ValueError("Coordenadas IMX500 fuera de rango; revisa orden y normalización del RPK.")
        yx = np.clip(xy, 0, 1)[[1, 0, 3, 2]]
        rectangle = convert(tuple(float(x) for x in yx))
        if hasattr(rectangle, "x"):
            x, y, w, h = rectangle.x, rectangle.y, rectangle.width, rectangle.height
        else:
            x, y, w, h = rectangle
        x1, y1 = max(0, float(x)), max(0, float(y))
        x2, y2 = min(width, float(x + w)), min(height, float(y + h))
        if x2 > x1 and y2 > y1:
            result.append(Detection((x1, y1, x2, y2), float(score), 0))
    return sorted(result, key=lambda item: item.confidence, reverse=True)[:max_detections]


class IMX500Camera(Picamera2Camera):
    def __init__(self, config):
        super().__init__(config)
        self.imx = None
        self.hardware_active = False
        self.last_tensor_at = 0.0

    def open(self) -> None:
        model = self.config.camera.imx500_model
        if not model:
            self._fallback("No se configuró un modelo RPK para el sensor.")
            return
        try:
            from picamera2 import Picamera2
            from picamera2.devices.imx500 import IMX500

            path = self.config.path(model)
            if not path.is_file() or path.suffix.lower() != ".rpk":
                raise ValueError("imx500_model debe apuntar a un archivo .rpk existente.")
            infos = Picamera2.global_camera_info()
            info = next(item for item in infos if item["Num"] == int(self.config.camera.source))
            self.imx = IMX500(str(path), camera_id=info["Id"])
            self.picam = Picamera2(self.imx.camera_num)
            intrinsics = self.imx.network_intrinsics
            if intrinsics and intrinsics.task not in (None, "object detection"):
                raise ValueError("El RPK debe ser un modelo de detección de objetos.")
            self._start()
            if self.config.camera.imx500_preserve_aspect_ratio:
                self.imx.set_auto_aspect_ratio()
            self.hardware_active = True
            self.model_status = "YOLO / IMX500: " + path.name
            self.last_tensor_at = time.monotonic()
        except Exception as exc:
            self.close()
            self._fallback(f"No se pudo activar el RPK ({type(exc).__name__}).")

    def _fallback(self, reason: str) -> None:
        if not self.config.camera.allow_cpu_fallback:
            raise CameraError(reason + " El fallback está desactivado.")
        log.warning("%s Se usará YOLO en el equipo con la misma cámara CSI.", reason)
        self.hardware_active = False
        self.model_status = "YOLO en equipo (fallback IMX500)"
        super().open()

    def _packet(self, image, metadata):
        packet = super()._packet(image, metadata)
        if not self.hardware_active:
            return packet
        try:
            outputs = self.imx.get_outputs(metadata, add_batch=True)
            if outputs is None:
                packet.inference_pending = True
                if time.monotonic() - self.last_tensor_at > self.config.camera.imx500_tensor_timeout_seconds:
                    raise ValueError("El sensor dejó de entregar tensores.")
                return packet
            cfg = self.config.camera
            packet.detections = decode_outputs(
                outputs,
                lambda box: self.imx.convert_inference_coords(box, metadata, self.picam),
                self.imx.get_input_size(),
                (image.shape[1], image.shape[0]),
                order=cfg.imx500_bbox_order,
                normalized=cfg.imx500_boxes_normalized,
                threshold=self.config.detection.confidence,
                person_class=cfg.imx500_person_class,
                max_detections=self.config.detection.max_detections,
            )
            self.last_tensor_at = time.monotonic()
            return packet
        except (ValueError, IndexError, TypeError) as exc:
            if not self.config.camera.allow_cpu_fallback:
                raise CameraError("No se pueden interpretar las salidas IMX500: " + str(exc)) from exc
            log.warning("Salida IMX500 incompatible: %s. Se activa YOLO en el equipo.", exc)
            self.hardware_active = False
            self.model_status = "YOLO en equipo (fallback de tensores IMX500)"
            packet.inference_pending = False
            packet.detections = None
            packet.discontinuity = True
            return packet

    def close(self) -> None:
        try:
            super().close()
        finally:
            self.hardware_active = False
            if self.imx is not None:
                # IMX500 no expone close; su descriptor es liberado al destruirlo.
                self.imx = None
