from pathlib import Path

import numpy as np
import pytest

from camera_counter.config import Config
from camera_counter.types import TrackedPerson
from camera_counter.visitors.recognizer import FaceRecognizer


def test_bundled_models_load_and_blank_frame_does_not_invent_faces():
    cfg = Config(base_dir=Path(__file__).resolve().parents[1])
    backend = FaceRecognizer(cfg)
    assert backend.model_id.endswith("0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79")
    frame = np.zeros((480, 640, 3), np.uint8)
    assert backend.extract(frame, [TrackedPerson(1, (0, 0, 640, 480), 0.9)], {1}) == {}


def test_missing_model_fails_with_installation_instructions(tmp_path):
    with pytest.raises(RuntimeError, match="download_face_models.py"):
        FaceRecognizer(Config(base_dir=tmp_path))
