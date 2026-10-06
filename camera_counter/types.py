"""Contratos independientes de YOLO y de las librerías de Raspberry Pi."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

Point = tuple[float, float]
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Detection:
    box: Box
    confidence: float
    class_id: int = 0


@dataclass(frozen=True)
class TrackedPerson:
    track_id: int
    box: Box
    confidence: float
    observed: bool = True

    @property
    def center(self) -> Point:
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2, (y1 + y2) / 2)


@dataclass
class FramePacket:
    image: Any
    sequence: int
    captured_at: float
    timestamp: datetime
    timeline: float
    detections: list[Detection] | None = None
    inference_pending: bool = False
    discontinuity: bool = False


@dataclass(frozen=True)
class CrossingEvent:
    track_id: int
    event_type: str
    confidence: float
    direction: str
    timestamp: datetime
    crossing_index: int = 0
