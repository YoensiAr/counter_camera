"""Regresión: el video mostraba Únicos=1, Entradas=26 y Salidas=26."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
import io
import sqlite3

import cv2
import numpy as np
import pytest

from camera_counter.app import CounterApplication
from camera_counter.config import Config, LineConfig, VisitorsConfig
from camera_counter.counting.line_counter import LineCounter
from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent
from camera_counter.utils.video import annotate
from camera_counter.visitors.store import VisitorStore
from camera_counter.web.routes import create_app

NOW = datetime(2026, 9, 10, 16, tzinfo=timezone.utc)
FACE = np.eye(1, 128, dtype=np.float32)[0]


def cross(repo, store, session, direction, index, *, track=2, now=NOW, face=FACE):
    event = CrossingEvent(track, direction, 0.95, "test", now, index)
    event_id = repo.record_crossing(event, session, "test", visitor_enabled=True)
    return event_id, store.classify(event_id, [face, face.copy()], now)


@pytest.fixture
def gallery(tmp_path):
    repo = Repository(tmp_path / "counter.db")
    store = VisitorStore(repo, VisitorsConfig(), tmp_path / "visitors.key", "test-sface")
    session = repo.start_session("test", NOW)
    yield repo, store, session
    repo.close()


@pytest.mark.parametrize("change_track", [False, True])
def test_26_round_trips_only_add_one_entry_and_one_exit(gallery, change_track):
    repo, store, session = gallery
    for trip in range(26):
        track = trip + 2 if change_track else 2
        for offset, direction in enumerate(("entry", "exit")):
            event_id, status = cross(repo, store, session, direction, trip * 2 + offset, track=track)
            assert status == ("new" if trip == 0 else "returning")
            assert store.classify(event_id, [FACE, FACE], NOW) == status  # Reintento idempotente.
            assert repo.stats(NOW)["occupancy"] == (1 if direction == "entry" else 0)
    stats = repo.stats(NOW)
    assert (stats["counted_entries_today"], stats["counted_exits_today"], stats["unique_visitors_today"]) == (1, 1, 1)
    assert (stats["returning_entries_today"], stats["returning_exits_today"]) == (25, 25)
    assert (stats["entries_today"], stats["exits_today"]) == (26, 26)  # Balance físico interno.
    history = repo.history("2026-09-10", "2026-09-10", "day")[0]
    assert (history["counted_entries"], history["counted_exits"], history["unique_visitors"]) == (1, 1, 1)
    events = list(repo.iter_events("2026-09-10", "2026-09-10"))
    assert len(events) == 52
    assert sum(event["counted"] for event in events) == 2


def test_direction_flags_survive_process_restart_and_occupancy_reset(tmp_path):
    path, key = tmp_path / "counter.db", tmp_path / "visitors.key"
    repo = Repository(path)
    store = VisitorStore(repo, VisitorsConfig(), key, "test")
    session = repo.start_session("test", NOW)
    for index, direction in enumerate(("entry", "exit")):
        cross(repo, store, session, direction, index)
    repo.close()
    reopened = Repository(path)
    try:
        store = VisitorStore(reopened, VisitorsConfig(), key, "test")
        session = reopened.start_session("test", NOW)
        reopened.reset_counters()
        for index, direction in enumerate(("entry", "exit")):
            assert cross(reopened, store, session, direction, index, track=94)[1] == "returning"
        stats = reopened.stats(NOW)
        assert (stats["counted_entries_today"], stats["counted_exits_today"], stats["occupancy"]) == (1, 1, 0)
    finally:
        reopened.close()


@pytest.mark.parametrize("window,hours", [("calendar_day", 24), ("hours", 4)])
def test_both_directions_become_available_after_expiry(gallery, window, hours):
    repo, store, session = gallery
    store.config.window, store.config.window_hours = window, hours
    for index, direction in enumerate(("entry", "exit")):
        cross(repo, store, session, direction, index)
    expiry = datetime.fromisoformat(repo.connection.execute("SELECT expires_at FROM visitors").fetchone()[0])
    for index, direction in enumerate(("entry", "exit"), 2):
        assert cross(repo, store, session, direction, index, now=expiry - timedelta(seconds=1))[1] == "returning"
    repo.purge_visitors(expiry)
    for index, direction in enumerate(("entry", "exit"), 4):
        assert cross(repo, store, session, direction, index, now=expiry)[1] == "new"
    stats = repo.stats(expiry)
    expected = 1 if window == "calendar_day" else 2
    assert stats["counted_entries_today"] == stats["counted_exits_today"] == expected


def test_first_observed_exit_does_not_consume_first_entry(gallery):
    repo, store, session = gallery
    assert cross(repo, store, session, "exit", 0)[1] == "new"
    assert repo.stats(NOW)["unique_visitors_today"] == 0
    assert cross(repo, store, session, "entry", 1)[1] == "new"
    assert cross(repo, store, session, "exit", 2)[1] == "returning"
    stats = repo.stats(NOW)
    assert stats["counted_entries_today"] == stats["counted_exits_today"] == stats["unique_visitors_today"] == 1


def test_different_people_each_get_one_count_per_direction(gallery):
    repo, store, session = gallery
    other = np.roll(FACE, 1)
    for track, face in ((2, FACE), (3, other), (44, FACE), (55, other)):
        for index, direction in enumerate(("entry", "exit")):
            cross(repo, store, session, direction, index, track=track, face=face)
    stats = repo.stats(NOW)
    assert stats["counted_entries_today"] == stats["counted_exits_today"] == stats["unique_visitors_today"] == 2


def test_event_retention_does_not_remove_live_direction_flags(gallery):
    repo, store, session = gallery
    store.config.window, store.config.window_hours = "hours", 48
    for index, direction in enumerate(("entry", "exit")):
        cross(repo, store, session, direction, index)
    tomorrow = NOW + timedelta(days=1)
    repo.prune(0, tomorrow)
    assert repo.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    for index, direction in enumerate(("entry", "exit"), 2):
        assert cross(repo, store, session, direction, index, now=tomorrow)[1] == "returning"
    stats = repo.stats(tomorrow)
    assert stats["counted_entries_today"] == stats["counted_exits_today"] == 0


def test_failure_rolls_back_existing_visitor_direction_flag(gallery):
    repo, store, session = gallery
    cross(repo, store, session, "entry", 0)
    event_id = repo.record_crossing(CrossingEvent(2, "exit", 0.95, "test", NOW, 1), session, "test", visitor_enabled=True)
    repo.connection.execute("CREATE TRIGGER fail BEFORE UPDATE ON visitor_events BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.classify(event_id, [FACE, FACE], NOW)
    assert repo.connection.execute("SELECT exit_counted FROM visitors").fetchone()[0] == 0
    assert repo.stats(NOW)["counted_exits_today"] == 0
    repo.connection.execute("DROP TRIGGER fail")
    assert store.classify(event_id, [FACE, FACE], NOW) == "new"
    assert repo.stats(NOW)["counted_exits_today"] == 1


def test_concurrent_exits_only_increment_once(tmp_path):
    path, key = tmp_path / "counter.db", tmp_path / "visitors.key"
    first, second = Repository(path), Repository(path)
    try:
        a = VisitorStore(first, VisitorsConfig(), key, "test")
        b = VisitorStore(second, VisitorsConfig(), key, "test")
        session = first.start_session("test", NOW)
        cross(first, a, session, "entry", 0)
        ids = [repo.record_crossing(CrossingEvent(track, "exit", 0.95, "test", NOW), session, "test", visitor_enabled=True)
               for track, repo in enumerate((first, second), 2)]
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda pair: pair[0].classify(pair[1], [FACE, FACE], NOW), zip((a, b), ids)))
        assert sorted(results) == ["new", "returning"]
        assert first.stats(NOW)["counted_exits_today"] == 1
    finally:
        first.close()
        second.close()


def test_video_overlay_uses_deduplicated_numbers(gallery, monkeypatch):
    repo, store, session = gallery
    for index in range(4):
        cross(repo, store, session, "entry" if index % 2 == 0 else "exit", index)
    texts = []
    real_put_text = cv2.putText

    def capture(image, text, *args, **kwargs):
        texts.append(text)
        return real_put_text(image, text, *args, **kwargs)

    monkeypatch.setattr(cv2, "putText", capture)
    counter = LineCounter(LineConfig(), 640, 480)
    frame = annotate(np.zeros((480, 640, 3), np.uint8), [], counter, repo.stats(NOW), 10, "USB")
    assert frame.shape == (480, 640, 3)
    assert "Unicos 1    Entradas 1    Salidas 1    Dentro 0" in texts


def test_http_summary_and_detail_agree_with_live_counters(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = "mock"
    runtime = CounterApplication(cfg)
    try:
        repo = runtime.repository
        now = datetime.now(timezone.utc)
        store = VisitorStore(repo, cfg.visitors, tmp_path / "key", "test")
        for index in range(5):
            cross(repo, store, runtime.session, "entry" if index % 2 == 0 else "exit", index, now=now)
        client = create_app(runtime).test_client()
        status = client.get("/api/status").json
        assert (status["counted_entries_today"], status["counted_exits_today"], status["occupancy"]) == (1, 1, 1)
        history = client.get("/api/history?group=day").json[0]
        assert (history["counted_entries"], history["counted_exits"], history["unique_visitors"]) == (1, 1, 1)
        summary = client.get("/reports/summary.csv?group=day")
        assert summary.status_code == 200
        row = list(csv.DictReader(io.StringIO(summary.text.lstrip("\ufeff"))))[0]
        assert (row["entradas"], row["salidas"], row["visitantes_unicos"]) == ("1", "1", "1")
        detail = client.get("/reports/events.csv")
        rows = list(csv.DictReader(io.StringIO(detail.text.lstrip("\ufeff"))))
        assert len(rows) == 5 and sum(int(row["suma_al_contador"]) for row in rows) == 2
        assert client.get("/reports/summary.csv?group=raw").status_code == 400
        assert client.get("/reports/summary.csv?start=oops").status_code == 400
    finally:
        runtime.close()


def test_v2_migration_preserves_faces_counts_and_raw_exit_evidence(tmp_path):
    path, key = tmp_path / "counter.db", tmp_path / "visitors.key"
    repo = Repository(path)
    store = VisitorStore(repo, VisitorsConfig(), key, "test")
    session = repo.start_session("test", NOW)
    for index, direction in enumerate(("entry", "exit", "entry", "exit")):
        cross(repo, store, session, direction, index)
    encrypted = repo.connection.execute("SELECT template FROM visitors").fetchone()[0]
    repo.close()
    # Reconstruye la estructura exacta de v2: solo entradas clasificadas,
    # sin bandera de conteo ni memoria de direcciones.
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM visitor_events WHERE event_id IN (SELECT id FROM events WHERE event_type='exit')")
        db.execute("ALTER TABLE visitor_events DROP COLUMN counted")
        db.execute("ALTER TABLE visitors DROP COLUMN entry_counted")
        db.execute("ALTER TABLE visitors DROP COLUMN exit_counted")
    for attempt in range(2):
        migrated = Repository(path)
        try:
            store = VisitorStore(migrated, VisitorsConfig(), key, "test")
            assert migrated.connection.execute("SELECT template FROM visitors").fetchone()[0] == encrypted
            assert migrated.stats(NOW)["counted_entries_today"] == 1
            assert migrated.stats(NOW)["entries"] == 2
            assert migrated.stats(NOW)["exits"] == 2 + attempt
            assert migrated.stats(NOW)["unverified_exits_today"] == 2
            assert migrated.stats(NOW)["counted_exits_today"] == attempt
            if attempt == 0:
                assert cross(migrated, store, session, "exit", 4)[1] == "new"
            assert migrated.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert migrated.connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            migrated.close()
    assert path.with_name(path.name + ".before-direction-counts-v2.1.bak").is_file()
