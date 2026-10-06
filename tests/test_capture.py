import queue

from camera_counter.cameras.capture import CaptureWorker
from camera_counter.cameras.mock_camera import MockCamera
from camera_counter.config import Config


def test_file_mode_preserves_all_frames_in_order(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.realtime = False
    camera = MockCamera(cfg, frames=25)
    worker = CaptureWorker(camera, cfg)
    worker.start()
    indices = []
    try:
        while True:
            try:
                packet = worker.queue.get(timeout=0.1)
                indices.append(packet.sequence)
            except queue.Empty:
                if worker.done.is_set():
                    break
    finally:
        worker.stop()
    assert indices == list(range(25))
    assert worker.dropped == 0
    assert not worker.thread.is_alive()


def test_live_queue_discards_oldest_and_stays_bounded(tmp_path):
    cfg = Config(base_dir=tmp_path)
    camera = MockCamera(cfg, frames=10)
    camera.lossless = False
    worker = CaptureWorker(camera, cfg)
    worker.start()
    worker.thread.join(timeout=3)
    worker.stop()
    assert worker.queue.qsize() == 2
    assert worker.dropped == 8
    assert [worker.queue.get_nowait().sequence for _ in range(2)] == [8, 9]
