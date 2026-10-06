"""OSNet compara apariencia corporal. No convierte ropa o color en identidad cierta."""

from __future__ import annotations

import hashlib

import cv2
import numpy as np


def body_vector(value) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    if vector.shape != (512,) or not np.isfinite(vector).all():
        raise ValueError("La referencia corporal requiere 512 valores finitos.")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-8:
        raise ValueError("Referencia corporal vacía.")
    return vector / norm


def overlap_fraction(a, b) -> float:
    """Cobertura respecto al menor cuerpo: detecta también oclusiones asimétricas."""
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    area = min(max(0, a[2] - a[0]) * max(0, a[3] - a[1]), max(0, b[2] - b[0]) * max(0, b[3] - b[1]))
    return intersection / area if area else 0.0


def crowded_tracks(people, threshold):
    observed = [p for p in people if p.observed]
    crowded = set()
    for i, first in enumerate(observed):
        for second in observed[i + 1:]:
            if overlap_fraction(first.box, second.box) >= threshold:
                crowded.update((first.track_id, second.track_id))
    return crowded


class BodyRecognizer:
    def __init__(self, config):
        self.settings = config.visitors
        cv2.setNumThreads(config.detection.cpu_threads)
        path = config.path(self.settings.body_model)
        if not path.is_file():
            raise RuntimeError("Falta el modelo corporal OSNet. Copia models/osnet_x0_25_msmt17.onnx del ZIP actualizado.")
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        with path.open("rb") as stream:
            self.model_id = "osnet-512-v1:" + hashlib.file_digest(stream, "sha256").hexdigest()
        self.net.setInput(np.zeros((1, 3, 256, 128), dtype=np.float32))
        body_vector(self.net.forward())

    def extract(self, frame, people, eligible: set[int]) -> dict[int, np.ndarray]:
        if not eligible:
            return {}
        settings = self.settings
        crowded = crowded_tracks(people, settings.body_max_overlap)
        height, width = frame.shape[:2]
        result = {}
        for person in people:
            if (not person.observed or person.track_id not in eligible or person.track_id in crowded
                    or person.confidence < settings.body_min_confidence):
                continue
            if not np.isfinite(person.box).all():
                continue
            x1, y1, x2, y2 = person.box
            area = max(0, x2 - x1) * max(0, y2 - y1)
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(width, int(np.ceil(x2))), min(height, int(np.ceil(y2)))
            if x2 - x1 < settings.body_min_width or y2 - y1 < settings.body_min_height:
                continue
            if area <= 0 or (x2 - x1) * (y2 - y1) / area < 0.8:
                continue
            crop = frame[y1:y2, x1:x2]
            # Medir a tamaño normalizado evita confundir textura de ruido con detalle útil.
            scaled = cv2.resize(crop, (128, 256), interpolation=cv2.INTER_LINEAR)
            gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
            if cv2.Laplacian(gray, cv2.CV_64F).var() < settings.body_min_sharpness:
                continue
            if np.percentile(gray, 95) - np.percentile(gray, 5) < 12:
                continue
            pixels = cv2.cvtColor(scaled, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            pixels = (pixels - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
            self.net.setInput(np.ascontiguousarray(pixels.transpose(2, 0, 1)[None]))
            result[person.track_id] = body_vector(self.net.forward().copy())
        return result
