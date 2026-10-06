"""Inferencia local con un modelo existente. Las descargas son una acción separada."""

import importlib.util
import logging
import os

from camera_counter.config import Config
from camera_counter.types import Detection
from camera_counter.utils.platform import is_raspberry_pi

log = logging.getLogger(__name__)


def configure_ultralytics(config: Config) -> None:
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["YOLO_OFFLINE"] = "true"
    os.environ["YOLO_VERBOSE"] = "false"
    os.environ["YOLO_CONFIG_DIR"] = str(config.path("data/ultralytics"))
    os.environ["WANDB_MODE"] = "disabled"
    try:
        from ultralytics import settings
    except ImportError as exc:
        raise RuntimeError("Falta Ultralytics/PyTorch. Instala las dependencias de tu plataforma.") from exc
    settings.update({"sync": False})


class YOLODetector:
    def __init__(self, config: Config):
        self.config = config
        configure_ultralytics(config)
        import torch
        from ultralytics import YOLO

        self.torch = torch
        torch.set_num_threads(config.detection.cpu_threads)
        model = config.detection.model
        if model == "auto":
            ncnn = config.path("models/yolo11n_ncnn_model")
            model = (
                "models/yolo11n_ncnn_model"
                if (is_raspberry_pi() and ncnn.is_dir() and importlib.util.find_spec("ncnn") is not None)
                else "models/yolo11n.pt"
            )
        path = config.path(model)
        if not path.exists():
            raise RuntimeError(
                "Falta el modelo local. Ejecuta python scripts/download_model.py o configura detection.model."
            )
        self.device = config.detection.device
        if self.device == "auto":
            self.device = "0" if torch.cuda.is_available() and path.suffix == ".pt" else "cpu"
        self.model = YOLO(str(path), task="detect")
        names = self.model.names
        if str(names.get(0, "") if isinstance(names, dict) else names[0]).lower() != "person":
            raise ValueError("El modelo YOLO debe usar clase COCO 0=person. Revisa detection.model.")
        self.name = path.name
        self.status = f"{self.name} / {self.device}"

    def detect(self, image) -> list[Detection]:
        cfg = self.config.detection
        arguments = dict(
            source=image,
            classes=[0],
            conf=cfg.confidence,
            iou=cfg.iou,
            imgsz=cfg.image_size,
            device=self.device,
            max_det=cfg.max_detections,
            verbose=False,
            save=False,
            stream=False,
        )
        try:
            result = self.model.predict(**arguments)[0]
        except RuntimeError:
            if self.device == "cpu" or not self.config.camera.allow_cpu_fallback:
                raise
            log.warning("Falló el acelerador del equipo; se reintenta la inferencia en CPU.")
            self.device = "cpu"
            self.status = f"{self.name} / cpu (fallback)"
            arguments["device"] = "cpu"
            result = self.model.predict(**arguments)[0]
        finally:
            # AutoBackend vuelve a elegir hasta 8 hilos al preparar CPU. Restaurar
            # el límite después de esa preparación evita saturar la Pi/equipos pequeños.
            if self.torch.get_num_threads() != cfg.cpu_threads:
                self.torch.set_num_threads(cfg.cpu_threads)
        if result.boxes is None:
            return []
        boxes = result.boxes.cpu().numpy()
        return [
            Detection(tuple(float(v) for v in box), float(score), 0)
            for box, score, cls in zip(boxes.xyxy, boxes.conf, boxes.cls)
            if int(cls) == 0
        ]
