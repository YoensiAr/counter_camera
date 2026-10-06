import time

import numpy as np
import pytest

from camera_counter.cameras.imx500_camera import IMX500Camera, decode_outputs
from camera_counter.config import Config


def convert(coords):
    y1, x1, y2, x2 = coords
    return x1 * 640, y1 * 480, (x2 - x1) * 640, (y2 - y1) * 480


def test_normalized_yolo_outputs_filter_person_and_map_coordinates():
    outputs = [np.array([[[0.1, 0.2, 0.4, 0.6], [0.3, 0.2, 0.5, 0.7]]]), np.array([[0.9, 0.9]]), np.array([[0, 2]])]
    detections = decode_outputs(outputs, convert, (640, 640), (640, 480))
    assert len(detections) == 1
    assert detections[0].box == pytest.approx((64, 96, 256, 288))


def test_pixel_yx_outputs_use_correct_width_and_height():
    outputs = [np.array([[[64, 64, 192, 256]]]), np.array([[0.9]]), np.array([[0]])]
    detections = decode_outputs(outputs, convert, (640, 320), (640, 480), order="yx", normalized=False)
    assert detections[0].box == pytest.approx((64, 96, 256, 288))


def test_rect_object_api_supported():
    class Rectangle:
        x, y, width, height = 10, 20, 30, 40

    outputs = [np.array([[0.1, 0.2, 0.4, 0.6]]), np.array([0.9]), np.array([0])]
    result = decode_outputs(outputs, lambda box: Rectangle(), (640, 640), (640, 480))
    assert result[0].box == (10, 20, 40, 60)


def test_raw_head_is_rejected():
    with pytest.raises(ValueError):
        decode_outputs([np.zeros((1, 84, 8400))], convert, (640, 640), (640, 480))


def test_missing_tensors_are_not_replayed(tmp_path):
    class Sensor:
        def get_outputs(self, metadata, add_batch):
            return None

    config = Config(base_dir=tmp_path)
    camera = IMX500Camera(config)
    camera.hardware_active = True
    camera.imx = Sensor()
    camera.last_tensor_at = time.monotonic()
    packet = camera._packet(np.zeros((480, 640, 3), np.uint8), {})
    assert packet.inference_pending
    assert packet.detections is None


def test_tensor_failure_activates_fallback(tmp_path):
    class Sensor:
        def get_outputs(self, *args, **kwargs):
            return []

        def get_input_size(self):
            return (640, 640)

    config = Config(base_dir=tmp_path)
    camera = IMX500Camera(config)
    camera.hardware_active = True
    camera.imx = Sensor()
    packet = camera._packet(np.zeros((480, 640, 3), np.uint8), {})
    assert not camera.hardware_active
    assert packet.detections is None
    assert packet.discontinuity


def test_native_request_released_even_on_parse_failure(tmp_path):
    from camera_counter.cameras.picamera2_camera import Picamera2Camera

    class Request:
        released = False

        def make_array(self, *args):
            return np.zeros((10, 10, 3), np.uint8)

        def get_metadata(self):
            raise ValueError("simulado")

        def release(self):
            self.released = True

    req = Request()

    class Camera:
        def capture_request(self, wait):
            return "job"

        def wait(self, job, timeout):
            return req

    camera = Picamera2Camera(Config(base_dir=tmp_path))
    camera.picam = Camera()
    with pytest.raises(RuntimeError):
        camera.read()
    assert req.released
