from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from camera_counter.config import Config
from camera_counter.counting.line_counter import LineCounter
from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent, TrackedPerson
from camera_counter.visitors.service import VisitorService

NOW = datetime(2026, 9, 10, 16, tzinfo=timezone.utc)
FACE = np.eye(1, 128, dtype=np.float32)[0]


class Backend:
    model_id = "test-sface"
    show_face = True
    fail = False

    def extract(self, frame, people, eligible):
        if self.fail:
            raise RuntimeError("modelo averiado")
        return {key: FACE.copy() for key in eligible} if self.show_face else {}


@pytest.fixture
def service(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = "usb"
    cfg.visitors.sample_interval_seconds = 0.1
    repo = Repository(tmp_path / "counter.db")
    backend = Backend()
    service = VisitorService(cfg, repo, backend=backend)
    service.start(NOW)
    session = repo.start_session("entrada", NOW)
    yield service, repo, session, backend
    service.finish()
    repo.close()


def person(track_id=1, y=60, observed=True):
    return TrackedPerson(track_id, (60, y - 30, 140, y + 30), 0.9, observed)


def observe(service, timeline, people=None):
    timestamp = NOW + timedelta(seconds=timeline)
    service.observe(None, [person()] if people is None else people, timeline, timestamp)
    service.flush(timeline, timestamp)


def crossing(service, session, track_id=1, timeline=1, index=0):
    return service.record(
        CrossingEvent(track_id, "entry", 0.9, "-1->+1", NOW + timedelta(seconds=timeline), index), session, timeline
    )


@pytest.mark.parametrize("new_track", [1, 77])
def test_complete_line_and_identity_pipeline_for_reentry(service, new_track):
    visitors, repo, session, backend = service
    line = visitors.config.line
    line.margin_px, line.cooldown_seconds = 5, 0.2
    counter = LineCounter(line, 200, 200)

    def walk(ys, track, start):
        for index, y in enumerate(ys):
            timeline = start + index * 0.2
            timestamp = NOW + timedelta(seconds=timeline)
            people = [person(track, y)]
            visitors.observe(None, people, timeline, timestamp)
            for event in counter.update(people, timeline, timestamp):
                visitors.record(event, session, timeline)
            visitors.flush(timeline, timestamp)

    walk([60] * 4 + [135] * 4 + [60] * 4, 1, 0)
    assert repo.stats(NOW)["occupancy"] == 0
    start = 2.4
    if new_track != 1:
        counter.update([], 8, NOW + timedelta(seconds=8))
        visitors.tick(8, NOW + timedelta(seconds=8))
        start = 8.2
    walk([60] * 4 + [135] * 4, new_track, start)
    stats = repo.stats(NOW)
    assert (stats["entries_today"], stats["exits_today"], stats["occupancy"]) == (2, 1, 1)
    assert (stats["unique_visitors_today"], stats["returning_entries_today"]) == (1, 1)
    assert (stats["counted_entries_today"], stats["counted_exits_today"]) == (1, 1)
    assert stats["pending_entries_today"] == 0
    walk([135] * 4 + [60] * 4, new_track, start + 1.6)
    stats = repo.stats(NOW)
    assert (stats["counted_entries_today"], stats["counted_exits_today"], stats["occupancy"]) == (1, 1, 0)
    assert stats["returning_exits_today"] == 1


def test_face_seen_after_crossing_can_resolve_pending_entry(service):
    visitors, repo, session, backend = service
    backend.show_face = False
    observe(visitors, 0)
    crossing(visitors, session)
    assert repo.stats(NOW)["pending_entries_today"] == 1
    backend.show_face = True
    observe(visitors, 1.2)
    observe(visitors, 1.5)
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert repo.stats(NOW)["pending_entries_today"] == 0


def test_missing_face_keeps_physical_count_and_never_invents_unique_visitor(service):
    visitors, repo, session, backend = service
    backend.show_face = False
    crossing(visitors, session)
    visitors.tick(10, NOW + timedelta(seconds=10))
    visitors.flush(10, NOW + timedelta(seconds=10))
    stats = repo.stats(NOW)
    assert stats["entries_today"] == stats["unverified_entries_today"] == 1
    assert stats["unique_visitors_today"] == stats["pending_entries_today"] == 0


def test_predicted_tracks_cannot_supply_face_evidence(service):
    visitors, repo, session, backend = service
    observe(visitors, 0, [person(observed=False)])
    observe(visitors, 0.4, [person(observed=False)])
    assert visitors.tracks == {}


def test_expired_samples_cannot_identify_a_later_crossing(service):
    visitors, repo, session, backend = service
    observe(visitors, 0)
    observe(visitors, 0.2)
    backend.show_face = False
    for t in range(1, 6):
        observe(visitors, t)
    assert len(visitors.tracks[1].samples) == 0
    crossing(visitors, session, timeline=5)
    visitors.flush(5, NOW + timedelta(seconds=5))
    assert repo.stats(NOW)["unique_visitors_today"] == 0


def test_backend_failure_is_visible_and_does_not_reuse_stale_face(service):
    visitors, repo, session, backend = service
    observe(visitors, 0)
    observe(visitors, 0.2)
    backend.fail = True
    observe(visitors, 0.5)
    crossing(visitors, session)
    assert "modelo averiado" in visitors.status(NOW)["error"]
    assert len(visitors.tracks[1].samples) == 0
    visitors.flush(10, NOW + timedelta(seconds=10))
    assert repo.stats(NOW)["unique_visitors_today"] == 0


def test_exit_alone_is_verified_without_inventing_an_entry(service):
    visitors, repo, session, backend = service
    observe(visitors, 0)
    observe(visitors, 0.2)
    visitors.record(CrossingEvent(1, "exit", 0.9, "+1->-1", NOW), session, 0.5)
    visitors.flush(0.5, NOW + timedelta(seconds=0.5))
    stats = repo.stats(NOW)
    assert stats["counted_exits_today"] == 1
    assert stats["counted_entries_today"] == stats["unique_visitors_today"] == 0


def test_exit_without_face_remains_unverified_and_does_not_add_to_exit_counter(service):
    visitors, repo, session, backend = service
    backend.show_face = False
    visitors.record(CrossingEvent(1, "exit", 0.9, "+1->-1", NOW), session, 0)
    assert repo.stats(NOW)["pending_exits_today"] == 1
    visitors.flush(9, NOW + timedelta(seconds=9))
    stats = repo.stats(NOW)
    assert stats["unverified_exits_today"] == stats["exits_today"] == 1
    assert stats["counted_exits_today"] == stats["pending_exits_today"] == 0


def test_restart_recovers_unfinished_decisions(service):
    visitors, repo, session, backend = service
    crossing(visitors, session)
    restarted = VisitorService(visitors.config, repo, backend=Backend())
    restarted.start(NOW + timedelta(seconds=5))
    assert repo.stats(NOW)["pending_entries_today"] == 0
    assert repo.stats(NOW)["unverified_entries_today"] == 1
    assert repo.stats(NOW)["unique_visitors_today"] == 0


def test_forget_removes_templates_and_ram_but_preserves_totals(service):
    visitors, repo, session, backend = service
    observe(visitors, 0)
    observe(visitors, 0.2)
    crossing(visitors, session)
    visitors.flush(1, NOW + timedelta(seconds=1))
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    visitors.forget()
    assert visitors.tracks == {} and visitors.pending == {}
    assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert repo.connection.execute("SELECT visitor_id FROM visitor_events").fetchone()[0] is None


def test_simulation_never_creates_keys_or_face_references(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = "mock"
    repo = Repository(tmp_path / "counter.db")
    service = VisitorService(cfg, repo)
    service.start(NOW)
    session = repo.start_session("test", NOW)
    crossing(service, session)
    assert service.status(NOW)["mode"] == "simulation"
    assert repo.stats(NOW)["unchecked_entries_today"] == 1
    assert not (tmp_path / "data/visitors.key").exists()
    repo.close()


def test_diagnostic_in_memory_never_writes_key_file(tmp_path):
    cfg = Config(base_dir=tmp_path)
    repo = Repository(":memory:")
    visitors = VisitorService(cfg, repo, backend=Backend())
    visitors.start(NOW)
    assert visitors.store is not None
    assert not (tmp_path / "data/visitors.key").exists()
    repo.close()


def test_cleanup_runs_without_any_faces_or_frames(service):
    visitors, repo, session, backend = service
    observe(visitors, 0)
    observe(visitors, 0.2)
    crossing(visitors, session)
    visitors.flush(1, NOW + timedelta(seconds=1))
    visitors.tick(86401, NOW + timedelta(days=1, seconds=1))
    assert visitors.status(NOW + timedelta(days=1))["active_references"] == 0
    assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
    assert visitors.tracks == {}
