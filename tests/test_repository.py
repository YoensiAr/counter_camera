from datetime import datetime, timedelta, timezone

from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent


NOW = datetime(2026, 9, 10, 16, tzinfo=timezone.utc)


def event(kind="entry", track=1, now=NOW):
    return CrossingEvent(track, kind, 0.91, "-1->+1", now)


def test_persistence_after_restart(tmp_path):
    path = tmp_path / "counts.sqlite3"
    r = Repository(path)
    first = r.start_session("entrada", NOW)
    r.record(event(), first, "entrada")
    r.end_session(first)
    r.close()
    reopened = Repository(path)
    second = reopened.start_session("entrada", NOW)
    assert first != second
    assert reopened.stats(NOW)["entries_today"] == 1
    assert reopened.stats(NOW)["occupancy"] == 1
    assert reopened.record(event(), second, "entrada")
    assert reopened.stats(NOW)["entries"] == 2
    reopened.close()


def test_transaction_deduplicates(tmp_path):
    r = Repository(tmp_path / "db")
    s = r.start_session("cam", NOW)
    assert r.record(event(), s, "cam") is True
    assert r.record(event(), s, "cam") is False
    assert r.stats(NOW)["entries"] == 1
    r.close()


def test_reset_preserves_history(tmp_path):
    r = Repository(tmp_path / "db")
    s = r.start_session("cam", NOW)
    r.record(event(), s, "cam")
    r.reset_counters()
    assert r.stats(NOW)["occupancy"] == 0
    assert r.stats(NOW)["entries_today"] == 0
    assert len(list(r.iter_events("2026-09-10", "2026-09-10"))) == 1
    r.record(event(track=2), s, "cam")
    assert r.stats(NOW)["entries_today"] == 1
    r.close()


def test_negative_occupancy_clamped_and_logged(tmp_path, caplog):
    r = Repository(tmp_path / "db")
    s = r.start_session("cam", NOW)
    r.record(event("exit"), s, "cam")
    assert r.stats(NOW)["occupancy"] == 0
    assert r.stats(NOW)["inconsistent"]
    assert "inconsistente" in caplog.text
    r.close()


def test_local_midnight_preserves_occupancy(tmp_path):
    r = Repository(tmp_path / "db")
    s = r.start_session("cam", NOW)
    previous = datetime(2026, 9, 10, 3, 59, tzinfo=timezone.utc)
    r.record(event(now=previous), s, "cam")
    assert r.stats(NOW)["entries_today"] == 0
    assert r.stats(NOW)["occupancy"] == 1
    r.close()


def test_retention_preserves_accumulated_balance(tmp_path):
    r = Repository(tmp_path / "db")
    s = r.start_session("cam", NOW - timedelta(days=100))
    r.record(event(now=NOW - timedelta(days=100)), s, "cam")
    r.end_session(s)
    r.prune(90, NOW)
    assert r.stats(NOW)["entries"] == 1
    assert list(r.iter_events("2026-01-01", "2026-12-31")) == []
    r.close()
