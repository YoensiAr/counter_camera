"""Memoria acotada de cada recorrido visible."""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from camera_counter.types import Point


class PersonState(str, Enum):
    UNKNOWN = "UNKNOWN"
    OUTSIDE = "OUTSIDE"
    CROSSING = "CROSSING"
    INSIDE = "INSIDE"
    COUNTED_ENTRY = "COUNTED_ENTRY"
    COUNTED_EXIT = "COUNTED_EXIT"


@dataclass
class TrackMemory:
    first_seen: float
    last_seen: float
    history: deque[Point]
    confidences: deque[float]
    state: PersonState = PersonState.UNKNOWN
    previous_position: Point | None = None
    stable_side: int = 0
    candidate_side: int = 0
    confirmations: int = 0
    intersected: bool = False
    direction: str = ""
    last_event_at: float = float("-inf")
    last_event_type: str = ""
    counted: set[str] = field(default_factory=set)
    crossing_index: int = 0

    @property
    def already_counted(self) -> bool:
        return bool(self.counted)
