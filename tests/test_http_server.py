import json
import queue
import socket
import threading
import urllib.request

import pytest

from camera_counter.app import CounterApplication
from camera_counter.config import Config


@pytest.mark.integration
def test_waitress_serves_status_video_and_stops_cleanly(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = "mock"
    cfg.web.host = "127.0.0.1"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        cfg.web.port = sock.getsockname()[1]
    app = CounterApplication(cfg)
    failures = queue.Queue()

    def run():
        try:
            app.run(max_frames=300)
        except Exception as exc:
            failures.put(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        with app.frames_condition:
            assert app.frames_condition.wait_for(lambda: app.latest_jpeg is not None or app.closed, timeout=15)
        assert not app.closed, list(failures.queue)
        url = f"http://127.0.0.1:{cfg.web.port}"
        with urllib.request.urlopen(url + "/api/status", timeout=3) as response:
            assert json.load(response)["running"] is True
        with urllib.request.urlopen(url + "/video_feed", timeout=3) as response:
            assert response.read(7) == b"--frame"
    finally:
        app.stop_event.set()
        thread.join(timeout=12)
    assert not thread.is_alive()
    assert failures.empty(), list(failures.queue)
