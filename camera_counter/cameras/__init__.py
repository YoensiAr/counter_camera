"""Selección de cámaras; los módulos específicos de Pi se cargan bajo demanda."""

from camera_counter.config import Config
from camera_counter.utils.platform import is_raspberry_pi


def make_camera(config: Config):
    kind = config.camera.type
    if kind == "browser":
        from .browser_camera import BrowserCamera

        return BrowserCamera(config)
    if kind == "mock":
        from .mock_camera import MockCamera

        return MockCamera(config)
    if kind == "auto":
        source = config.camera.source
        if isinstance(source, str) and not source.isdecimal():
            kind = "rtsp" if "://" in source else "video"
        elif is_raspberry_pi():
            try:
                from picamera2 import Picamera2

                cameras = Picamera2.global_camera_info()
                selected = next((item for item in cameras if item.get("Num") == int(source)), None)
                if selected:
                    kind = "imx500" if "imx500" in selected.get("Model", "").lower() else "csi"
                else:
                    kind = "usb"
            except ImportError:
                kind = "usb"
        else:
            kind = "usb"
    if kind in {"imx500", "csi", "picamera2"}:
        if not is_raspberry_pi():
            raise RuntimeError("La cámara CSI/IMX500 requiere Raspberry Pi OS. Usa --camera usb o --simulate aquí.")
        if kind == "imx500":
            from .imx500_camera import IMX500Camera

            return IMX500Camera(config)
        from .picamera2_camera import Picamera2Camera

        return Picamera2Camera(config)
    from .opencv_camera import OpenCVCamera

    return OpenCVCamera(config, kind)
