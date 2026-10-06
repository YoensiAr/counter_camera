"""Regresiones de salidas que ocurren dentro de la pausa de una entrada."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from camera_counter.config import Config, LineConfig
from camera_counter.counting.line_counter import LineCounter
from camera_counter.database.repository import Repository
from camera_counter.types import TrackedPerson
from camera_counter.visitors.service_hybrid import HybridVisitorService

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


def person(y, track_id=1, x=100):
    return TrackedPerson(track_id, (x - 40, y - 90, x + 40, y + 90), .95)


@pytest.mark.parametrize("direction", ["positive", "negative"])
@pytest.mark.parametrize("first", ["entry", "exit"])
def test_confirmed_opposite_crossing_is_not_blocked_by_cooldown(direction, first):
    cfg = LineConfig(margin_px=5, confirmation_frames=3, cooldown_seconds=10, entry_to=direction)
    counter = LineCounter(cfg, 200, 200)
    inside, outside = (140, 60) if direction == "positive" else (60, 140)
    a, b = (outside, inside) if first == "entry" else (inside, outside)
    emitted = []
    for n, y in enumerate([a] * 3 + [b] * 3 + [a] * 20):
        t = n * .1
        emitted += counter.update([person(y)], t, NOW + timedelta(seconds=t))
    assert [e.event_type for e in emitted] == [first, "exit" if first == "entry" else "entry"]
    assert [e.crossing_index for e in emitted] == [1, 2]
    assert (emitted[1].timestamp - emitted[0].timestamp).total_seconds() == pytest.approx(.3)


def test_same_direction_still_has_cooldown_and_no_delayed_event():
    counter = LineCounter(LineConfig(margin_px=5, cooldown_seconds=10), 200, 200)
    # Rodear el extremo no es un cruce válido de salida. La siguiente entrada
    # repite la misma dirección y conserva la protección contra duplicación.
    positions = [(100, 60)] * 3 + [(100, 140)] * 3 + [(195, 140)] * 3
    positions += [(195, 60)] * 3 + [(100, 60)] * 3 + [(100, 140)] * 3
    emitted = []
    for n, (x, y) in enumerate(positions):
        emitted += counter.update([person(y, x=x)], n * .1, NOW)
    # Sin un nuevo cruce, dejar vencer el plazo no debe emitir nada.
    for n in range(120):
        emitted += counter.update([person(140)], 1.8 + n * .1, NOW)
    assert [e.event_type for e in emitted] == ["entry"]


def test_two_exit_observations_then_disappearance_do_not_invent_a_confirmed_exit():
    counter = LineCounter(LineConfig(margin_px=5, cooldown_seconds=1), 200, 200)
    emitted = []
    for n, y in enumerate([60] * 3 + [140] * 3 + [60] * 2):
        emitted += counter.update([person(y)], n * .1, NOW)
    emitted += counter.update([], .8, NOW)
    emitted += counter.update([], 4, NOW)
    assert [e.event_type for e in emitted] == ["entry"]
    assert counter.lost_inside == {1}


class NoFace:
    model_id = "exit-test-face"

    def extract(self, frame, people, eligible):
        return {}


class Body:
    model_id = "exit-test-body"

    def extract(self, frame, people, eligible):
        vector = np.eye(1, 512, dtype=np.float32)[0]
        return {p.track_id: vector.copy() for p in people if p.track_id in eligible}


@pytest.mark.parametrize("trips", [1, 10])
def test_fast_back_facing_exits_keep_occupancy_and_unique_counts_correct(tmp_path, trips):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = "video"
    cfg.line = LineConfig(margin_px=5, cooldown_seconds=1)
    cfg.visitors.sample_interval_seconds = .1
    repo = Repository(tmp_path / "counter.db")
    service = HybridVisitorService(cfg, repo, backend=NoFace(), body_backend=Body())
    service.start(NOW)
    session = repo.start_session("exit-regression", NOW)
    counter = LineCounter(cfg.line, 200, 200)
    try:
        ys = [60] * 3 + ([140] * 3 + [60] * 3) * trips
        for n, y in enumerate(ys):
            t = n * .1
            timestamp = NOW + timedelta(seconds=t)
            people = [person(y)]
            service.observe(None, people, t, timestamp)
            counter.invalidate(service.take_invalidated_tracks())
            for event in counter.update(people, t, timestamp):
                service.record(event, session, t)
            service.flush(t, timestamp)
        service.finish("test_complete", timestamp)
        stats = repo.stats(NOW)
        assert (stats["entries"], stats["exits"], stats["occupancy"]) == (trips, trips, 0)
        assert (stats["unique_visitors_today"], stats["counted_entries_today"], stats["counted_exits_today"]) == (1, 1, 1)
        assert stats["unverified_entries_today"] == stats["unverified_exits_today"] == 0
        assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 1
    finally:
        repo.close()
