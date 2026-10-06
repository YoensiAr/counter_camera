import numpy as np
import pytest

from camera_counter.app import CounterApplication
from camera_counter.cameras.mock_camera import MockCamera
from camera_counter.config import Config
from camera_counter.detection.tracker import PersonTracker
from camera_counter.types import Detection


pytestmark = pytest.mark.integration


@pytest.fixture
def cfg(tmp_path):
    config = Config(base_dir=tmp_path)
    config.camera.type = "mock"
    config.camera.realtime = False
    config.web.enabled = False
    return config


@pytest.mark.parametrize("tracker", ["bytetrack", "botsort"])
def test_complete_mock_pipeline_with_real_tracker(cfg, tracker):
    cfg.tracking.type = tracker
    app = CounterApplication(cfg, camera=MockCamera(cfg, frames=240))
    result = app.run()
    assert result["processed_frames"] == 240
    assert result["entries"] == 2
    assert result["exits"] == 1
    assert result["occupancy"] == 1
    assert not app.capture.thread.is_alive()
    assert app.repository.closed
    assert not list(cfg.base_dir.glob("recordings/*.mp4"))


def test_bytetrack_recovers_occlusion_without_new_id(cfg):
    tracker = PersonTracker(cfg)
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    ids = []
    for i in range(30):
        detections = [] if 10 <= i <= 12 else [Detection((60, 20 + i * 2, 100, 100 + i * 2), 0.9)]
        ids.extend(p.track_id for p in tracker.update(detections, image, i * 0.05))
    assert len(set(ids)) == 1
    assert len(ids) >= 25


def test_low_confidence_boxes_recover_existing_track(cfg):
    tracker = PersonTracker(cfg)
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    ids = []
    for i in range(20):
        detections = [Detection((60, 20 + i, 100, 100 + i), 0.2 if 5 <= i <= 10 else 0.9)]
        people = tracker.update(detections, image, i * 0.05)
        assert len(people) == 1
        ids.append(people[0].track_id)
    assert len(set(ids)) == 1


def test_long_absence_gets_new_id(cfg):
    tracker = PersonTracker(cfg)
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    detections = [Detection((60, 20, 100, 100), 0.9)]
    original = tracker.update(detections, image, 0)[0].track_id
    tracker.update([], image, 10)
    tracker.update(detections, image, 10.1)
    later = tracker.update(detections, image, 10.2)[0].track_id
    assert later != original


def test_inference_stride_still_counts_from_observations(cfg):
    cfg.detection.inference_stride = 3
    app = CounterApplication(cfg, camera=MockCamera(cfg, frames=240))
    result = app.run()
    assert (result["entries"], result["exits"]) == (2, 1)


def test_actual_mock_frames_have_detections_without_ids(cfg):
    camera = MockCamera(cfg, frames=2)
    camera.open()
    packet = camera.read()
    assert packet.image.shape == (480, 640, 3)
    assert packet.detections
    assert not hasattr(packet.detections[0], "track_id")
    camera.read()
    assert camera.read() is None
    camera.close()
