import os
import time

import cv2
import numpy as np

from camera_counter.config import Config
from camera_counter.utils.video import Recorder


def test_recording_rotates_playable_segments(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.recording.enabled = True
    cfg.recording.segment_seconds = 5
    cfg.camera.fps = 10
    recorder = Recorder(cfg)
    image = np.zeros((120, 160, 3), np.uint8)
    for index in range(100):
        image[:] = index
        recorder.write(image.copy(), index / 10)
    recorder.close()
    files = list((tmp_path / "recordings").glob("counter_*.mp4"))
    assert len(files) == 2
    total_frames = 0
    for file in files:
        capture = cv2.VideoCapture(str(file))
        assert capture.isOpened()
        total_frames += int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        assert capture.read()[0]
        capture.release()
    assert total_frames == 100


def test_recording_disabled_writes_nothing(tmp_path):
    recorder = Recorder(Config(base_dir=tmp_path))
    recorder.write(np.zeros((120, 160, 3), np.uint8), 0)
    recorder.close()
    assert not (tmp_path / "recordings").exists()


def test_retention_does_not_delete_other_videos(tmp_path):
    cfg = Config(base_dir=tmp_path)
    directory = tmp_path / "recordings"
    directory.mkdir()
    own = directory / "counter_old.mp4"
    other = directory / "family.mp4"
    for path in (own, other):
        path.write_bytes(b"example")
        old = time.time() - 90 * 86400
        os.utime(path, (old, old))
    recorder = Recorder(cfg)
    recorder.cleanup()
    assert not own.exists()
    assert other.exists()
