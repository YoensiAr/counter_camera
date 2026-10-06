"""Interfaz de captura. None significa fin de un archivo; un fallo lanza CameraError."""

from abc import ABC, abstractmethod

from camera_counter.types import FramePacket


class CameraError(RuntimeError):
    pass


class BaseCamera(ABC):
    finite: bool = False
    lossless: bool = False
    status: str = "detenida"
    model_status: str = "YOLO en equipo"

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read(self) -> FramePacket | None: ...

    @abstractmethod
    def close(self) -> None: ...
