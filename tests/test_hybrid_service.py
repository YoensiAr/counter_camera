from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from camera_counter.config import Config
from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent, TrackedPerson
from camera_counter.visitors.service_hybrid import HybridVisitorService

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
FACE = np.eye(1, 128, dtype=np.float32)[0]
BODY = np.eye(1, 512, dtype=np.float32)[0]


class Backend:
    def __init__(self, kind, show=True):
        self.model_id = kind
        self.vector = FACE if kind == "face" else BODY
        self.show = show
        self.fail = False
        self.per_track = {}

    def extract(self, frame, people, eligible):
        if self.fail:
            raise RuntimeError("test backend failure")
        return {key: self.per_track.get(key, self.vector).copy() for key in eligible} if self.show else {}


@pytest.fixture
def service(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = "usb"
    cfg.visitors.sample_interval_seconds = .1
    repo = Repository(tmp_path / "counter.db")
    face, body = Backend("face", False), Backend("body")
    visitors = HybridVisitorService(cfg, repo, backend=face, body_backend=body)
    visitors.start(NOW)
    session = repo.start_session("test", NOW)
    yield visitors, repo, session, face, body
    visitors.finish()
    repo.close()


def person(track=1, x=100, observed=True):
    return TrackedPerson(track, (x - 40, 30, x + 40, 230), .95, observed)


def observe(service, t, people=None):
    visitors = service[0]
    timestamp = NOW + timedelta(seconds=t)
    visitors.observe(None, [person()] if people is None else people, t, timestamp)
    visitors.flush(t, timestamp)


def sample(service, start=0, people=None):
    for delta in (0, .2, .4):
        observe(service, start + delta, people)


def cross(service, t=.5, index=1, kind="entry", track=1):
    visitors, _, session, _, _ = service
    stamp = NOW + timedelta(seconds=t)
    visitors.record(CrossingEvent(track, kind, .95, "test", stamp, index), session, t)
    visitors.flush(t, stamp)


def test_entry_and_back_facing_exit_without_any_face(service):
    visitors, repo, _, _, body = service
    sample(service)
    cross(service)
    # Giro gradual: enseña vistas coherentes, sin repetir la entrada ni necesitar una cara.
    for i, angle in enumerate(np.linspace(0, np.pi / 2, 20)):
        body.vector = BODY * np.cos(angle) + np.roll(BODY, 1) * np.sin(angle)
        observe(service, .8 + .2 * i)
    cross(service, 4.7, 2, "exit")
    cross(service, 4.75, 3)
    stats = repo.stats(NOW)
    assert (stats["unique_visitors_today"], stats["counted_entries_today"], stats["counted_exits_today"]) == (1, 1, 1)
    assert len(visitors.pending) == 0
    assert repo.connection.execute("SELECT COUNT(*) FROM visitor_bodies").fetchone()[0] == 1


def test_disappearance_and_new_tracker_id_match_body(service):
    visitors, repo, _, _, _ = service
    sample(service)
    cross(service)
    observe(service, 4, [])
    assert visitors.tracks == {}
    sample(service, 4.1, [person(77)])
    cross(service, 4.6, 2, track=77)
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert repo.stats(NOW)["returning_entries_today"] == 1
    assert visitors.tracks[77].identity is not None


def test_recycled_id_does_not_reuse_stale_identity(service):
    visitors, repo, _, _, body = service
    sample(service)
    cross(service)
    observe(service, 4, [])
    body.vector = np.roll(BODY, 1)
    sample(service, 4.1)
    cross(service, 4.6, 2)
    assert repo.stats(NOW)["unique_visitors_today"] == 2
    assert visitors.tracks[1].evidence == "body"


def test_teleport_invalidates_track_and_pending_event(service):
    visitors, repo, _, _, body = service
    body.show = False
    observe(service, 0)
    cross(service, .1)
    assert len(visitors.pending) == 1
    observe(service, .2, [person(x=1000)])
    assert not visitors.pending
    assert visitors.take_invalidated_tracks() == {1}
    assert repo.stats(NOW)["unverified_entries_today"] == 1


def test_simultaneously_visible_equal_bodies_are_ambiguous(service):
    visitors, repo, _, _, _ = service
    sample(service)
    cross(service)
    sample(service, .8, [person(), person(2, x=400)])
    cross(service, 1.3, 2, track=2)
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert repo.stats(NOW)["pending_entries_today"] == 1
    assert visitors.tracks[2].identity is None


def test_overlap_stops_learning_and_cannot_carry_identity_through_occlusion(service):
    visitors, repo, _, _, _ = service
    sample(service)
    cross(service)
    observe(service, .8, [person(), person(2, x=110)])
    assert visitors.tracks[1].identity is None
    assert visitors.tracks[1].crowded
    assert not visitors.tracks[1].bodies and not visitors.tracks[2].bodies
    cross(service, .9, 2, "exit")
    assert repo.stats(NOW)["counted_exits_today"] == 0
    assert repo.stats(NOW)["unverified_exits_today"] == 1


def test_abrupt_appearance_change_does_not_silently_create_new_identity(service):
    visitors, repo, _, _, body = service
    sample(service)
    cross(service)
    body.vector = np.roll(BODY, 1)
    sample(service, .8)
    cross(service, 1.3, 2)
    assert visitors.tracks[1].uncertain_identity
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert repo.stats(NOW)["pending_entries_today"] == 1


def test_face_backend_failure_still_allows_body_but_reports_degradation(service):
    visitors, repo, _, face, _ = service
    face.fail = True
    sample(service)
    cross(service)
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert "facial" in visitors.status(NOW)["error"]


def test_body_backend_failure_does_not_reuse_previous_identity(service):
    visitors, repo, _, _, body = service
    sample(service)
    cross(service)
    body.fail = True
    observe(service, .8)
    cross(service, .9, 2, "exit")
    assert visitors.tracks[1].identity is None
    assert repo.stats(NOW)["counted_exits_today"] == 0
    assert "corporal" in visitors.status(NOW)["error"]


def test_frames_without_body_or_face_cannot_refresh_identity_forever(service):
    visitors, repo, _, _, body = service
    sample(service)
    cross(service)
    body.show = False
    for t in (1, 2, 3, 4, 5):
        observe(service, t)
    cross(service, 5.1, 2, "exit")
    assert repo.stats(NOW)["counted_exits_today"] == 0
    assert visitors.track_labels()[1] == "sin verificar"


def test_predicted_tracks_supply_neither_body_nor_continuity(service):
    visitors, _, _, _, _ = service
    sample(service, people=[person(observed=False)])
    assert visitors.tracks == {}


def test_clock_rewind_invalidates_temporal_evidence(service):
    visitors, repo, _, _, _ = service
    sample(service)
    cross(service)
    observe(service, .1)
    assert visitors.tracks[1].identity is None
    assert len(visitors.tracks[1].bodies) <= 1
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_forget_clears_encrypted_body_templates_and_cache(service):
    visitors, repo, _, _, _ = service
    sample(service)
    cross(service)
    observe(service, .8)
    visitors.forget()
    assert repo.connection.execute("SELECT COUNT(*) FROM visitor_bodies").fetchone()[0] == 0
    assert not visitors.store._cache and not visitors.tracks
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_body_references_purge_without_camera_frames(service):
    visitors, repo, _, _, _ = service
    sample(service)
    cross(service)
    visitors.tick(86400, NOW + timedelta(days=1))
    assert repo.connection.execute("SELECT COUNT(*) FROM visitor_bodies").fetchone()[0] == 0
    assert not visitors.store._cache


def test_body_pending_crossing_times_out_without_fabricating_identity(service):
    visitors, repo, _, _, body = service
    body.show = False
    sample(service)
    cross(service)
    for t in np.arange(.6, 10, .2):
        observe(service, float(t))
    assert repo.stats(NOW)["pending_entries_today"] == 0
    assert repo.stats(NOW)["unverified_entries_today"] == 1
    assert repo.stats(NOW)["counted_entries_today"] == 0


def test_real_body_model_loads_and_rejects_blank_image():
    from camera_counter.visitors.body import BodyRecognizer
    cfg = Config(base_dir=Path(__file__).resolve().parents[1])
    recognizer = BodyRecognizer(cfg)
    assert recognizer.extract(np.zeros((480, 640, 3), np.uint8), [person()], {1}) == {}
