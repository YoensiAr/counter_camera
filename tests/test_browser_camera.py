import cv2
import numpy as np

from camera_counter.cameras.browser_camera import BrowserCamera
from camera_counter.config import Config


def test_browser_camera_decodes_and_resizes_jpeg():
    cfg = Config()
    cfg.camera.type = "browser"
    cfg.camera.width = 640
    cfg.camera.height = 480
    camera = BrowserCamera(cfg)
    camera.open()

    image = np.zeros((240, 320, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    camera.submit_jpeg(encoded.tobytes())

    packet = camera.read()
    assert packet is not None
    assert packet.image.shape[:2] == (480, 640)
    assert packet.sequence == 1
    assert camera.status == "cámara web conectada"
    camera.close()
