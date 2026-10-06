from dataclasses import replace
from datetime import datetime, timezone
import sqlite3

import numpy as np
import pytest

from camera_counter.app import CounterApplication
from camera_counter.config import Config, LineConfig, VisitorsConfig
from camera_counter.counting.line_counter import LineCounter
from camera_counter.database.repository import Repository
from camera_counter.types import CrossingEvent, TrackedPerson
from camera_counter.visitors.body import BodyRecognizer
from camera_counter.visitors.hybrid import HybridStore
from camera_counter.web.routes import create_app

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


def person(x, y=100, track=1):
    return TrackedPerson(track, (x - 10, y - 20, x + 10, y + 20), .95)


def feed(counter, xs, start=0, y=100):
    events = []
    for i, x in enumerate(xs):
        events.extend(counter.update([person(x, y)], start + .1 * i, NOW))
    return events


def test_movements_outside_access_rectangle_do_not_count():
    cfg = LineConfig(p1=[.5, .1], p2=[.5, .9], margin_px=3, confirmation_frames=2, roi=[.3, .3, .7, .7])
    counter = LineCounter(cfg, 200, 200)
    assert not feed(counter, [70, 70, 130, 130], y=40)
    assert len(feed(counter, [70, 70, 130, 130], start=1)) == 1


def test_leaving_roi_resets_path_without_fabricating_crossing():
    cfg = LineConfig(p1=[.5, .1], p2=[.5, .9], margin_px=3, confirmation_frames=2, roi=[.3, .3, .7, .7])
    counter = LineCounter(cfg, 200, 200)
    assert not feed(counter, [70, 70, 20, 20, 130, 130])


@pytest.mark.parametrize("anchor,y", [("head", 86), ("center", 100), ("feet", 120)])
def test_crossing_anchor_matches_annotation(anchor, y):
    counter = LineCounter(LineConfig(anchor=anchor), 200, 200)
    assert counter.anchor(person(100)) == (100, y)


def test_reused_tracker_id_after_expiry_has_unique_event_sequence():
    cfg = LineConfig(p1=[.5, .9], p2=[.5, .1], margin_px=3, confirmation_frames=2)
    counter = LineCounter(cfg, 200, 200)
    first = feed(counter, [70, 70, 130, 130])[0]
    counter.expire(10)
    second = feed(counter, [70, 70, 130, 130], start=11)[0]
    assert second.crossing_index > first.crossing_index


@pytest.mark.parametrize("roi", [[.1, .2], [0, 0, 0, 1], [.5, .5, .4, .8], [-1, 0, 1, 1], [0, 0, float('nan'), 1], [True, 0, 1, 1]])
def test_malformed_roi_rejected(roi):
    with pytest.raises(ValueError):
        LineConfig(roi=roi).validate()


def test_roi_not_intersecting_line_is_rejected():
    with pytest.raises(ValueError, match="atravesar"):
        LineConfig(roi=[.1, .1, .3, .3]).validate()


@pytest.mark.parametrize("changes", [
    {"mode": "anything"}, {"mode": {}}, {"body_min_samples": 1}, {"body_max_views": 100},
    {"body_match_threshold": float('nan')}, {"body_new_threshold": .95},
    {"body_max_overlap": 0}, {"continuity_gap_seconds": 20}, {"body_min_confidence": True},
])
def test_invalid_hybrid_configuration_rejected(changes):
    with pytest.raises(ValueError):
        replace(VisitorsConfig(), **changes).validate()


def test_transaction_failure_does_not_leave_orphan_body_or_increment(tmp_path):
    repo = Repository(tmp_path / 'counter.db')
    try:
        store = HybridStore(repo, VisitorsConfig(), tmp_path / 'key', 'face', 'body')
        session = repo.start_session('test', NOW)
        event = repo.record_crossing(CrossingEvent(1, 'entry', .9, 'test', NOW), session, 'test', visitor_enabled=True)
        repo.connection.execute("CREATE TRIGGER fail BEFORE UPDATE ON visitor_events BEGIN SELECT RAISE(ABORT,'test'); END")
        body = np.eye(1, 512, dtype=np.float32)[0]
        with pytest.raises(sqlite3.IntegrityError):
            store.classify(event, [], NOW, body_samples=[body] * 3)
        assert repo.connection.execute('SELECT COUNT(*) FROM visitors').fetchone()[0] == 0
        assert repo.connection.execute('SELECT COUNT(*) FROM visitor_bodies').fetchone()[0] == 0
        assert repo.stats(NOW)['counted_entries_today'] == 0
        assert repo.connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        repo.close()


def test_occupancy_uncertainty_survives_restart_and_reset_clears_it(tmp_path):
    path = tmp_path / 'counter.db'
    repo = Repository(path)
    repo.mark_occupancy_uncertain('tracking_interrupted_inside')
    repo.close()
    reopened = Repository(path)
    try:
        assert reopened.stats(NOW)['occupancy_uncertain']
        reopened.reset_counters()
        assert not reopened.stats(NOW)['occupancy_uncertain']
    finally:
        reopened.close()


def test_losing_already_entered_track_marks_occupancy_quality():
    cfg = LineConfig(p1=[.5, .9], p2=[.5, .1], margin_px=3, confirmation_frames=2)
    counter = LineCounter(cfg, 200, 200)
    assert feed(counter, [70, 70, 130, 130])[0].event_type == 'entry'
    counter.expire(10)
    assert counter.lost_inside == {1}


def test_access_zone_is_persisted_through_web_api(tmp_path):
    cfg = Config(base_dir=tmp_path)
    cfg.camera.type = 'mock'
    runtime = CounterApplication(cfg)
    try:
        app = create_app(runtime)
        client = app.test_client()
        headers = {'X-CSRF-Token': app.config['CSRF_TOKEN']}
        response = client.post('/api/line', json={'roi': [.1, .3, .9, .8], 'anchor': 'feet'}, headers=headers)
        assert response.status_code == 200
        assert response.json['line']['anchor'] == 'feet'
        assert runtime.config.line.roi == [.1, .3, .9, .8]
        assert 'Delimitar acceso' in client.get('/').text
        assert client.post('/api/line', json={'roi': [0, 0]}, headers=headers).status_code == 400
    finally:
        runtime.close()


def test_body_backend_rejects_overlapping_and_predicted_people():
    recognizer = BodyRecognizer.__new__(BodyRecognizer)
    recognizer.settings = VisitorsConfig()
    frame = np.random.default_rng(4).integers(0, 255, (240, 320, 3), dtype=np.uint8)
    people = [TrackedPerson(1, (20, 10, 130, 230), .95), TrackedPerson(2, (30, 15, 140, 235), .95),
              TrackedPerson(3, (150, 10, 280, 230), .95, False)]
    # Sin net: el intento de extraer una plantilla de cualquiera de estos cuerpos fallaría.
    assert recognizer.extract(frame, people, {1, 2, 3}) == {}
