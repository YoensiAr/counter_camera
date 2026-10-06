import sys

import pytest

from camera_counter.cameras import make_camera
from camera_counter.config import Config, load_config


def test_unknown_keys_fail_early(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("camera:\n  unknow_option: 1\n")
    with pytest.raises(ValueError):
        load_config(path)


def test_paths_relative_to_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("storage:\n  database: data/file.db\n")
    cfg = load_config(path)
    assert cfg.path(cfg.storage.database) == tmp_path / "data/file.db"


def test_mock_does_not_import_picamera(monkeypatch):
    monkeypatch.delitem(sys.modules, "picamera2", raising=False)
    config = Config()
    config.camera.type = "mock"
    make_camera(config)
    assert "picamera2" not in sys.modules


@pytest.mark.parametrize("value", [0, -1, 1.5, True, 1000])
def test_bad_frame_stride_rejected(value):
    config = Config()
    config.detection.inference_stride = value
    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize(
    "option,value",
    [
        ("enabled", "true"),
        ("min_samples", 1),
        ("min_samples", 2.5),
        ("max_identities", 0),
        ("match_threshold", float("nan")),
        ("min_face_pixels", True),
        ("detector_model", ""),
        ("sample_interval_seconds", 4),
        ("window", "months"),
    ],
)
def test_bad_face_settings_fail_early(option, value):
    config = Config()
    setattr(config.visitors, option, value)
    with pytest.raises(ValueError):
        config.validate()
