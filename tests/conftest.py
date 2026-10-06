from datetime import datetime, timezone

import pytest

from camera_counter.config import LineConfig
from camera_counter.counting.line_counter import LineCounter
from camera_counter.types import TrackedPerson


NOW = datetime(2026, 9, 10, 15, tzinfo=timezone.utc)


def person(track_id=1, x=100, y=50, observed=True):
    return TrackedPerson(track_id, (x - 15, y - 25, x + 15, y + 25), 0.92, observed)


@pytest.fixture
def counter():
    return LineCounter(
        LineConfig(p1=[0.1, 0.5], p2=[0.9, 0.5], margin_px=5, confirmation_frames=3, cooldown_seconds=0.2), 200, 200
    )


def feed(counter, ys, track_id=1, x=100, start=0):
    events = []
    for index, y in enumerate(ys):
        events.extend(counter.update([person(track_id, x, y)], start + index * 0.1, NOW))
    return events
