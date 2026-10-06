from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import numpy as np
import pytest

from camera_counter.config import VisitorsConfig
from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent
from camera_counter.visitors.store import VisitorStore, expires_at, normalize

NOW = datetime(2026, 9, 10, 16, tzinfo=timezone.utc)


def face(index=0):
    result = np.zeros(128, dtype=np.float32)
    result[index] = 1
    return result


@pytest.fixture
def gallery(tmp_path):
    repo = Repository(tmp_path / "counter.db")
    store = VisitorStore(repo, VisitorsConfig(), tmp_path / "visitors.key", "test-sface")
    session = repo.start_session("entrada", NOW)
    yield repo, store, session
    repo.close()


def enter(repo, session, track=1, now=NOW, index=0):
    event = CrossingEvent(track, "entry", 0.9, "-1->+1", now, index)
    return repo.record_crossing(event, session, "entrada", visitor_enabled=True)


def identify(store, event_id, vector=None, now=NOW):
    vector = face() if vector is None else vector
    return store.classify(event_id, [vector, vector.copy()], now)


def test_same_face_different_track_and_session_is_not_counted_again(gallery):
    repo, store, session = gallery
    assert identify(store, enter(repo, session)) == "new"
    other_session = repo.start_session("entrada", NOW)
    assert identify(store, enter(repo, other_session, 94)) == "returning"
    stats = repo.stats(NOW)
    assert stats["unique_visitors_today"] == 1
    assert stats["returning_entries_today"] == 1
    assert stats["entries_today"] == 2


def test_persistent_gallery_survives_restarting_process(tmp_path):
    database, key = tmp_path / "counter.db", tmp_path / "visitors.key"
    repo = Repository(database)
    session = repo.start_session("entrada", NOW)
    store = VisitorStore(repo, VisitorsConfig(), key, "sface")
    identify(store, enter(repo, session))
    repo.end_session(session)
    repo.close()
    reopened = Repository(database)
    store = VisitorStore(reopened, VisitorsConfig(), key, "sface")
    session = reopened.start_session("entrada", NOW)
    assert identify(store, enter(reopened, session, 991)) == "returning"
    assert reopened.stats(NOW)["unique_visitors_today"] == 1
    reopened.close()


def test_different_faces_are_different_visitors(gallery):
    repo, store, session = gallery
    assert identify(store, enter(repo, session), face(0)) == "new"
    assert identify(store, enter(repo, session, 2), face(1)) == "new"
    assert repo.stats(NOW)["unique_visitors_today"] == 2


def test_same_track_can_exit_and_return_without_corrupting_occupancy(gallery):
    repo, store, session = gallery
    assert identify(store, enter(repo, session, index=1)) == "new"
    assert repo.record(CrossingEvent(1, "exit", 0.9, "+1->-1", NOW, 2), session, "entrada")
    assert repo.stats(NOW)["occupancy"] == 0
    assert identify(store, enter(repo, session, index=3)) == "returning"
    assert repo.stats(NOW)["occupancy"] == 1
    assert repo.stats(NOW)["unique_visitors_today"] == 1
    assert enter(repo, session, index=3) is None  # Reintento del mismo evento.


def test_calendar_day_uses_local_midnight_and_deletes_links(gallery):
    repo, store, session = gallery
    before = datetime(2026, 9, 11, 3, 59, tzinfo=timezone.utc)
    after = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)
    assert identify(store, enter(repo, session, now=before), now=before) == "new"
    assert expires_at(before, store.config, repo.zone) == after
    assert repo.purge_visitors(after) == 1
    row = repo.connection.execute("SELECT status,visitor_id FROM visitor_events").fetchone()
    assert tuple(row) == ("new", None)
    assert identify(store, enter(repo, session, 2, after), now=after) == "new"
    assert repo.stats(after)["unique_visitors_today"] == 1
    assert repo.stats(before)["unique_visitors_today"] == 1


def test_rolling_window_is_anchored_to_first_entry_not_last_return(gallery):
    repo, store, session = gallery
    store.config.window, store.config.window_hours = "hours", 4
    identify(store, enter(repo, session))
    later = NOW + timedelta(hours=3)
    assert identify(store, enter(repo, session, 2, later), now=later) == "returning"
    expiry = repo.connection.execute("SELECT expires_at FROM visitors").fetchone()[0]
    assert datetime.fromisoformat(expiry) == NOW + timedelta(hours=4)
    later = NOW + timedelta(hours=4)
    repo.purge_visitors(later)
    assert identify(store, enter(repo, session, 3, later), now=later) == "new"
    assert repo.stats(later)["unique_visitors_today"] == 2


def test_midnight_pending_entry_cannot_enroll_in_wrong_day(gallery):
    repo, store, session = gallery
    before = datetime(2026, 9, 11, 3, 59, 59, tzinfo=timezone.utc)
    after = before + timedelta(seconds=2)
    assert identify(store, enter(repo, session, now=before), now=after) == "unverified"
    assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0


def test_ambiguous_face_is_not_merged_or_registered_as_new(gallery):
    repo, store, session = gallery
    identify(store, enter(repo, session), face(0))
    identify(store, enter(repo, session, 2), face(1))
    ambiguous = normalize(face(0) + face(1))
    assert identify(store, enter(repo, session, 3), ambiguous) == "unverified"
    assert repo.stats(NOW)["unique_visitors_today"] == 2
    assert repo.stats(NOW)["unverified_entries_today"] == 1


def test_uncertain_face_is_not_silently_counted_as_new(gallery):
    repo, store, session = gallery
    identify(store, enter(repo, session))
    uncertain = face(0) * 0.43 + face(1) * np.sqrt(1 - 0.43**2)
    assert identify(store, enter(repo, session, 2), uncertain) == "unverified"
    assert repo.stats(NOW)["unique_visitors_today"] == 1


def test_capacity_does_not_evict_valid_reference_and_cause_duplicates(gallery):
    repo, store, session = gallery
    store.config.max_identities = 1
    identify(store, enter(repo, session))
    assert identify(store, enter(repo, session, 2), face(1)) == "unverified"
    assert identify(store, enter(repo, session, 3)) == "returning"


def test_templates_are_encrypted_and_never_in_reports(gallery):
    repo, store, session = gallery
    identify(store, enter(repo, session))
    row = repo.connection.execute("SELECT template FROM visitors").fetchone()[0]
    assert face().tobytes() not in row
    assert store.cipher.decrypt(row) == face().tobytes()
    report = next(repo.iter_events("2026-09-10", "2026-09-10"))
    assert "template" not in report and "visitor_id" not in report
    assert report["visitor_status"] == "new"


def test_missing_key_fails_instead_of_resetting_identity_memory(gallery, tmp_path):
    repo, store, session = gallery
    identify(store, enter(repo, session))
    (tmp_path / "visitors.key").unlink()
    with pytest.raises(RuntimeError, match="Falta la clave"):
        VisitorStore(repo, store.config, tmp_path / "visitors.key", "test-sface")


def test_physical_reset_does_not_count_old_visitor_again(gallery):
    repo, store, session = gallery
    identify(store, enter(repo, session))
    repo.reset_counters()
    assert identify(store, enter(repo, session, 2)) == "returning"
    stats = repo.stats(NOW)
    assert stats["unique_visitors_today"] == 1
    assert stats["entries_today"] == 1
    history = repo.history("2026-09-10", "2026-09-10", "day")[0]
    assert (history["unique_visitors"], history["returning_entries"], history["entries"]) == (1, 1, 2)


def test_registration_and_unique_decision_rollback_together(gallery):
    repo, store, session = gallery
    event_id = enter(repo, session)
    repo.connection.execute("CREATE TRIGGER fail BEFORE UPDATE ON visitor_events BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        identify(store, event_id)
    assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
    assert repo.stats(NOW)["unique_visitors_today"] == 0
    assert repo.stats(NOW)["pending_entries_today"] == 1


def test_concurrent_connections_only_register_one_identity(tmp_path):
    database, key = tmp_path / "counter.db", tmp_path / "visitors.key"
    first, second = Repository(database), Repository(database)
    a = VisitorStore(first, VisitorsConfig(), key, "sface")
    b = VisitorStore(second, VisitorsConfig(), key, "sface")
    e1 = enter(first, first.start_session("entrada", NOW))
    e2 = enter(second, second.start_session("entrada", NOW), 2)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda pair: identify(*pair), [(a, e1), (b, e2)]))
    assert sorted(results) == ["new", "returning"]
    assert first.stats(NOW)["unique_visitors_today"] == 1
    first.close()
    second.close()


@pytest.mark.parametrize("sample", [np.zeros(128), np.ones(127), np.full(128, np.nan), np.full(128, np.inf)])
def test_invalid_vectors_are_rejected(gallery, sample):
    repo, store, session = gallery
    with pytest.raises(ValueError):
        identify(store, enter(repo, session), sample)
    assert repo.stats(NOW)["unique_visitors_today"] == 0


def test_mixed_samples_from_two_people_are_unverified(gallery):
    repo, store, session = gallery
    assert store.classify(enter(repo, session), [face(0), face(1)], NOW) == "unverified"


def test_old_event_migration_preserves_data(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.executescript("""
        CREATE TABLE sessions(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,ended_at TEXT,source TEXT NOT NULL);
        INSERT INTO sessions VALUES('old','2026-09-10T16:00:00+00:00',NULL,'entrada');
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,local_day TEXT NOT NULL,
        local_hour TEXT NOT NULL,event_type TEXT NOT NULL,track_id INTEGER NOT NULL,source TEXT NOT NULL,
        confidence REAL NOT NULL,direction TEXT NOT NULL,session_id TEXT NOT NULL REFERENCES sessions(id),
        UNIQUE(session_id,track_id,event_type));
        INSERT INTO events VALUES(1,'2026-09-10T16:00:00+00:00','2026-09-10','2026-09-10T12:00:00-04:00',
        'entry',7,'entrada',0.9,'-1->+1','old');
        CREATE TABLE counters(singleton INTEGER PRIMARY KEY,entries INTEGER NOT NULL DEFAULT 0,
        exits INTEGER NOT NULL DEFAULT 0,reset_event_id INTEGER NOT NULL DEFAULT 0,reset_at TEXT);
        INSERT INTO counters VALUES(1,1,0,0,NULL);
        """)
    repo = Repository(database)
    assert repo.stats(NOW)["entries"] == 1
    assert repo.stats(NOW)["unchecked_entries_today"] == 1
    assert enter(repo, "old", 7, index=1) is not None
    assert repo.stats(NOW)["entries"] == 2
    assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert database.with_name("legacy.db.before-visitors-v2.bak").is_file()
    repo.close()


def test_model_change_cannot_silently_double_count_existing_gallery(gallery, tmp_path):
    repo, store, session = gallery
    identify(store, enter(repo, session))
    with pytest.raises(RuntimeError, match="otro modelo"):
        VisitorStore(repo, store.config, tmp_path / "visitors.key", "different-model")


def test_policy_update_recomputes_expiry_from_first_entry(gallery):
    repo, store, session = gallery
    identify(store, enter(repo, session))
    settings = VisitorsConfig(window="hours", window_hours=1)
    store.set_window(settings, NOW + timedelta(minutes=30))
    row = repo.connection.execute("SELECT expires_at FROM visitors").fetchone()[0]
    assert datetime.fromisoformat(row) == NOW + timedelta(hours=1)
    store.set_window(settings, NOW + timedelta(hours=1))
    assert repo.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
