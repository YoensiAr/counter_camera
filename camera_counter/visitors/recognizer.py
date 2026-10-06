"""YuNet detecta rostros; SFace obtiene 128 valores en CPU mediante OpenCV DNN."""

from __future__ import annotations

import hashlib

import cv2
import numpy as np

from camera_counter.visitors.store import normalize


def assign_faces(faces, people, min_face_pixels: int) -> dict[int, np.ndarray]:
    """Solo asociaciones inequívocas: una cara por cuerpo y un cuerpo por cara."""
    candidates: dict[int, list] = {}
    for face in faces:
        if len(face) != 15 or not np.isfinite(face).all():
            continue
        x, y, w, h = face[:4]
        if min(w, h) < min_face_pixels:
            continue
        cx, cy = x + w / 2, y + h / 2
        owners = []
        for person in people:
            if not person.observed:
                continue
            x1, y1, x2, y2 = person.box
            # Se exige que la cara esté en la mitad superior del cuerpo y casi contenida.
            overlap = max(0, min(x + w, x2) - max(x, x1)) * max(0, min(y + h, y2) - max(y, y1))
            if x1 < cx < x2 and y1 <= cy <= y1 + (y2 - y1) * 0.55 and overlap / (w * h) >= 0.9:
                owners.append(person.track_id)
        if len(owners) == 1:
            candidates.setdefault(owners[0], []).append(face)
    return {track_id: group[0] for track_id, group in candidates.items() if len(group) == 1}


class FaceRecognizer:
    def __init__(self, config):
        self.settings = config.visitors
        cv2.setNumThreads(config.detection.cpu_threads)
        detector = config.path(self.settings.detector_model)
        recognizer = config.path(self.settings.recognizer_model)
        for model in (detector, recognizer):
            if not model.is_file():
                raise RuntimeError(
                    f"Falta {model.name}. Ejecuta scripts/download_face_models.py con el Python del entorno."
                )
        if not hasattr(cv2, "FaceDetectorYN_create") or not hasattr(cv2, "FaceRecognizerSF_create"):
            raise RuntimeError(
                "OpenCV no incluye YuNet/SFace. Instala requirements-windows.txt o requirements-raspberrypi.txt."
            )
        self.detector = cv2.FaceDetectorYN_create(
            str(detector),
            "",
            (320, 320),
            self.settings.detection_threshold,
            0.3,
            5000,
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        self.recognizer = cv2.FaceRecognizerSF_create(
            str(recognizer),
            "",
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        with recognizer.open("rb") as stream:
            self.model_id = "sface-128-v1:" + hashlib.file_digest(stream, "sha256").hexdigest()
        # Detecta modelos incompatibles al arrancar, antes de registrar entradas.
        self.detector.detect(np.zeros((320, 320, 3), dtype=np.uint8))
        normalize(self.recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8)))

    def extract(self, frame, people, eligible: set[int]) -> dict[int, np.ndarray]:
        if not eligible:
            return {}
        height, width = frame.shape[:2]
        scale = min(1.0, self.settings.detection_max_side / max(height, width))
        small = (
            cv2.resize(frame, (max(32, round(width * scale)), max(32, round(height * scale)))) if scale < 1 else frame
        )
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        if faces is None:
            return {}
        faces = faces.copy()
        # Coordenadas y landmarks vuelven al fotograma original antes de alinear.
        faces[:, [0, 2, 4, 6, 8, 10, 12]] *= width / small.shape[1]
        faces[:, [1, 3, 5, 7, 9, 11, 13]] *= height / small.shape[0]
        faces = [
            face
            for face in faces
            if face[-1] >= self.settings.detection_threshold
            and face[0] >= 0
            and face[1] >= 0
            and face[0] + face[2] <= width
            and face[1] + face[3] <= height
        ]
        assigned = assign_faces(faces, people, self.settings.min_face_pixels)
        features = {}
        for track_id, face in assigned.items():
            if track_id not in eligible:
                continue
            x, y, w, h = face[:4].astype(int)
            crop = frame[y : y + h, x : x + w]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if cv2.Laplacian(gray, cv2.CV_64F).var() < self.settings.min_sharpness:
                continue
            eyes = np.asarray(face[4:8]).reshape(2, 2)
            nose = face[8:10]
            # Descartar perfiles extremos/landmarks inestables; no inferir identidad por ropa.
            eye_distance = float(np.linalg.norm(eyes[0] - eyes[1]))
            if eye_distance < w * 0.18 or abs(float(nose[0] - eyes[:, 0].mean())) > eye_distance * 0.8:
                continue
            aligned = self.recognizer.alignCrop(frame, face)
            features[track_id] = normalize(self.recognizer.feature(aligned).copy())
        return features
