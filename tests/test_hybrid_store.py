from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from camera_counter.config import VisitorsConfig
from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent
from camera_counter.visitors.hybrid import HybridStore
from camera_counter.visitors.store import VisitorStore

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
FACE = np.eye(1, 128, dtype=np.float32)[0]
BODY = np.eye(1, 512, dtype=np.float32)[0]


@pytest.fixture
def gallery(tmp_path):
    repo = Repository(tmp_path / "counter.db")
    store = HybridStore(repo, VisitorsConfig(), tmp_path / "key", "face-test", "body-test")
    session = repo.start_session("test", NOW)
    yield repo, store, session
    repo.close()


def crossing(gallery, index=1, kind="entry", face=None, body=BODY, now=NOW, **kwargs):
    repo, store, session = gallery
    event_id = repo.record_crossing(CrossingEvent(index, kind, .95, "test", now, index), session, "test", visitor_enabled=True)
    result = store.classify(event_id, [] if face is None else [face, face], now,
                            body_samples=[] if body is None else [body] * 3, **kwargs)
    return event_id, result


def test_body_only_enrollment_and_reentries_in_both_directions(gallery):
    repo, store, _ = gallery
    for index, direction in enumerate(("entry", "exit", "entry", "exit"), 1):
        event, result = crossing(gallery, index, direction)
        assert result == ("new" if index <= 2 else "returning")
        assert store.event_identity(event)[1] == "body"
    stats = repo.stats(NOW)
    assert (stats["counted_entries_today"], stats["counted_exits_today"], stats["unique_visitors_today"], stats["occupancy"]) == (1, 1, 1, 0)
    assert repo.connection.execute("SELECT face_ready FROM visitors").fetchone()[0] == 0


def test_body_reference_and_flags_survive_restart(gallery, tmp_path):
    repo, store, _ = gallery
    crossing(gallery)
    repo.close()
    reopened = Repository(tmp_path / "counter.db")
    try:
        store = HybridStore(reopened, VisitorsConfig(), tmp_path / "key", "face-test", "body-test")
        session = reopened.start_session("test", NOW)
        assert crossing((reopened, store, session), 2)[1] == "returning"
        assert reopened.stats(NOW)["unique_visitors_today"] == 1
    finally:
        reopened.close()


def test_body_can_gain_a_face_without_creating_another_visitor(gallery):
    repo, store, _ = gallery
    event, _ = crossing(gallery)
    identity = store.event_identity(event)[0]
    assert crossing(gallery, 2, face=FACE)[1] == "returning"
    assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 1
    assert repo.connection.execute("SELECT face_ready FROM visitors").fetchone()[0] == 1
    assert store.match([FACE, FACE], [], NOW).visitor_id == identity


def test_face_anchored_track_learns_a_back_view(gallery):
    repo, store, _ = gallery
    event, _ = crossing(gallery, face=FACE)
    identity = store.event_identity(event)[0]
    back = np.roll(BODY, 1)
    assert store.remember(identity, [FACE, FACE], [back] * 3, NOW, learn_body=True)
    assert crossing(gallery, 2, "exit", body=back)[1] == "new"
    assert crossing(gallery, 3, body=back)[1] == "returning"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_untrusted_body_match_cannot_drift_the_gallery(gallery):
    _, store, _ = gallery
    event, _ = crossing(gallery)
    identity = store.event_identity(event)[0]
    foreign = np.roll(BODY, 1)
    store.remember(identity, [], [foreign] * 3, NOW, learn_body=False)
    assert store.match([], [foreign] * 3, NOW).kind == "new"


def test_similar_clothes_but_different_faces_are_not_merged(gallery):
    repo, _, _ = gallery
    crossing(gallery, face=FACE)
    assert crossing(gallery, 2, face=np.roll(FACE, 1))[1] == "new"
    assert repo.stats(NOW)["unique_visitors_today"] == 2


def test_two_similar_body_candidates_remain_pending(gallery):
    repo, _, _ = gallery
    crossing(gallery, face=FACE)
    similar = .90 * BODY + np.sqrt(1 - .90 ** 2) * np.roll(BODY, 1)
    crossing(gallery, 2, face=np.roll(FACE, 1), body=similar)
    ambiguous = BODY + similar
    event, result = crossing(gallery, 3, body=ambiguous)
    assert result == "pending"
    row = repo.connection.execute("SELECT reason,counted FROM visitor_events WHERE event_id=?", (event,)).fetchone()
    assert tuple(row) == ("ambiguous_body", 0)


def test_uncertain_body_does_not_get_registered_as_new(gallery):
    repo, _, _ = gallery
    crossing(gallery)
    candidate = .70 * BODY + np.sqrt(1 - .70 ** 2) * np.roll(BODY, 1)
    assert crossing(gallery, 2, body=candidate)[1] == "pending"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_pending_body_can_later_be_resolved_by_face(gallery):
    repo, store, _ = gallery
    crossing(gallery, face=FACE)
    candidate = .70 * BODY + np.sqrt(1 - .70 ** 2) * np.roll(BODY, 1)
    event, result = crossing(gallery, 2, body=candidate)
    assert result == "pending"
    assert store.classify(event, [FACE, FACE], NOW, body_samples=[candidate] * 3) == "returning"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_visible_identity_cannot_be_assigned_to_two_tracks(gallery):
    repo, store, _ = gallery
    event, _ = crossing(gallery)
    identity = store.event_identity(event)[0]
    assert crossing(gallery, 2, excluded={identity})[1] == "pending"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_clear_face_conflict_invalidates_continuity_hint(gallery):
    _, store, _ = gallery
    event, _ = crossing(gallery, face=FACE)
    identity = store.event_identity(event)[0]
    other = np.roll(FACE, 1)
    assert store.match([other, other], [BODY] * 3, NOW, hint=identity).kind == "conflict"


def test_moderate_face_noise_does_not_break_observed_continuity(gallery):
    _, store, _ = gallery
    event, _ = crossing(gallery, face=FACE)
    identity = store.event_identity(event)[0]
    noisy = .4 * FACE + np.sqrt(1 - .4 ** 2) * np.roll(FACE, 1)
    result = store.match([noisy, noisy], [BODY] * 3, NOW, hint=identity)
    assert result.visitor_id == identity and result.evidence == "continuity"


@pytest.mark.parametrize("window,hours", [("calendar_day", 24), ("hours", 2)])
def test_body_and_face_references_share_expiry(gallery, window, hours):
    repo, store, _ = gallery
    store.config.window, store.config.window_hours = window, hours
    event, _ = crossing(gallery)
    identity = store.event_identity(event)[0]
    expiry = datetime.fromisoformat(repo.connection.execute("SELECT expires_at FROM visitors").fetchone()[0])
    store.remember(identity, [], [BODY] * 3, NOW + timedelta(minutes=30), learn_body=True)
    assert datetime.fromisoformat(repo.connection.execute("SELECT expires_at FROM visitors").fetchone()[0]) == expiry
    repo.purge_visitors(expiry)
    assert repo.connection.execute("SELECT COUNT(*) FROM visitor_bodies").fetchone()[0] == 0
    assert store.match([], [], expiry, hint=identity).kind == "wait"
    assert crossing(gallery, 2, now=expiry)[1] == "new"


def test_no_body_evidence_cannot_reenroll_a_legacy_face(gallery):
    repo, _, _ = gallery
    crossing(gallery, face=FACE, body=None)
    event, result = crossing(gallery, 2)
    assert result == "pending"
    assert repo.connection.execute("SELECT reason FROM visitor_events WHERE event_id=?", (event,)).fetchone()[0] == "reference_without_body"


def test_face_only_mode_does_not_duplicate_old_body_identity(gallery, tmp_path):
    repo, _, session = gallery
    crossing(gallery)
    face_store = VisitorStore(repo, VisitorsConfig(mode="face"), tmp_path / "key", "face-test")
    event = repo.record_crossing(CrossingEvent(8, "entry", .9, "test", NOW), session, "test", visitor_enabled=True)
    assert face_store.classify(event, [FACE, FACE], NOW) == "unverified"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_body_gallery_is_encrypted_and_bounded(gallery):
    repo, store, _ = gallery
    event, _ = crossing(gallery, face=FACE)
    identity = store.event_identity(event)[0]
    for i in range(20):
        store.remember(identity, [FACE, FACE], [np.roll(BODY, i)] * 3, NOW, learn_body=True)
    blob = repo.connection.execute("SELECT template FROM visitor_bodies").fetchone()[0]
    assert BODY.tobytes() not in blob
    raw = store.cipher.decrypt(blob)
    assert 512 * 4 <= len(raw) <= store.config.body_max_views * 512 * 4
    assert np.frombuffer(raw, dtype="<f4").reshape(-1, 512)[0] @ BODY > .99


def test_body_capacity_cannot_evict_an_active_visitor(gallery):
    repo, store, _ = gallery
    store.config.max_identities = 1
    crossing(gallery)
    assert crossing(gallery, 2, body=np.roll(BODY, 1))[1] == "unverified"
    assert crossing(gallery, 3)[1] == "returning"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


@pytest.mark.parametrize("bad", [np.zeros(512), np.ones(511), np.full(512, np.nan), np.full(512, np.inf)])
def test_invalid_body_vectors_never_count(gallery, bad):
    repo, _, _ = gallery
    with pytest.raises(ValueError):
        crossing(gallery, body=bad)
    assert repo.stats(NOW)["counted_entries_today"] == 0


def test_changed_body_model_fails_instead_of_forgetting_people(gallery, tmp_path):
    repo, _, _ = gallery
    crossing(gallery)
    with pytest.raises(RuntimeError, match="otro modelo"):
        HybridStore(repo, VisitorsConfig(), tmp_path / "key", "face-test", "other-body")


def test_concurrent_body_entries_share_one_identity(tmp_path):
    path, key = tmp_path / "counter.db", tmp_path / "key"
    first, second = Repository(path), Repository(path)
    try:
        a = HybridStore(first, VisitorsConfig(), key, "face", "body")
        b = HybridStore(second, VisitorsConfig(), key, "face", "body")
        sa, sb = first.start_session("a", NOW), second.start_session("b", NOW)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda g: crossing(g)[1], [(first, a, sa), (second, b, sb)]))
        assert sorted(results) == ["new", "returning"]
        assert first.stats(NOW)["unique_visitors_today"] == 1
    finally:
        first.close()
        second.close()
