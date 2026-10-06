from datetime import datetime, timezone

import pytest

from camera_counter.app import CounterApplication
from camera_counter.config import Config, load_config
from camera_counter.types import CrossingEvent
from camera_counter.web.routes import create_app


@pytest.fixture
def web(tmp_path):
    config = Config(base_dir=tmp_path)
    config.camera.type = "mock"
    runtime = CounterApplication(config)
    application = create_app(runtime)
    application.testing = True
    client = application.test_client()
    yield runtime, application, client
    runtime.close()


def test_dashboard_and_status(web):
    runtime, app, client = web
    page = client.get("/")
    assert page.status_code == 200
    assert "Cada visita cuenta." in page.text
    assert client.get("/api/status").json["occupancy"] == 0
    assert client.get("/static/app.js").status_code == 200


def test_stream_tracks_active_viewers(web):
    runtime, _, _ = web
    runtime.latest_jpeg = b"jpeg"
    runtime.jpeg_sequence = 1
    stream = runtime.stream()

    assert b"jpeg" in next(stream)
    assert runtime.stream_clients == 1

    stream.close()
    assert runtime.stream_clients == 0


def test_mutations_require_csrf_and_confirmation(web):
    runtime, app, client = web
    assert client.post("/api/reset", json={"confirm": True}).status_code == 403
    headers = {"X-CSRF-Token": app.config["CSRF_TOKEN"]}
    assert client.post("/api/reset", json={}, headers=headers).status_code == 400
    assert client.get("/api/reset").status_code == 405
    assert client.post("/api/reset", json={"confirm": True}, headers=headers).status_code == 200


def test_line_persisted_after_restart(web):
    runtime, app, client = web
    line = {"p1": [0.2, 0.4], "p2": [0.8, 0.4], "entry_to": "negative"}
    response = client.post("/api/line", json=line, headers={"X-CSRF-Token": app.config["CSRF_TOKEN"]})
    assert response.status_code == 200
    reloaded = load_config(runtime.config.base_dir / "config.yaml")
    assert reloaded.line.p1 == [0.2, 0.4]
    assert reloaded.line.entry_to == "negative"


@pytest.mark.parametrize(
    "line",
    [
        {"p1": [2, 0.5]},
        {"p1": [0.9, 0.5]},
        {"p1": [float("nan"), 0.5]},
        {"confirmation_frames": 1},
        {"entry_to": "abajo"},
    ],
)
def test_invalid_line_rejected(web, line):
    runtime, app, client = web
    response = client.post("/api/line", json=line, headers={"X-CSRF-Token": app.config["CSRF_TOKEN"]})
    assert response.status_code == 400


def test_csv_keeps_history_after_reset_and_escapes_cells(web):
    runtime, app, client = web
    now = datetime.now(timezone.utc)
    event = CrossingEvent(1, "entry", 0.9, "-1->+1", now)
    runtime.repository.record(event, runtime.session, "=formula")
    runtime.reset_counters()
    csv = client.get("/reports/events.csv")
    assert csv.status_code == 200
    assert "'=" in csv.text
    assert "entrada" in csv.text
    assert "attachment" in csv.headers["Content-Disposition"]


def test_report_range_validated(web):
    _, _, client = web
    assert client.get("/api/history?start=oops").status_code == 400
    assert client.get("/api/history?group=raw").status_code == 400


def test_recording_toggle_defaults_off(web):
    runtime, app, client = web
    assert runtime.config.recording.enabled is False
    headers = {"X-CSRF-Token": app.config["CSRF_TOKEN"]}
    assert client.post("/api/recording", json={"enabled": "true"}, headers=headers).status_code == 400
    assert client.post("/api/recording", json={"enabled": True}, headers=headers).status_code == 200
    assert runtime.config.recording.enabled is True


def test_optional_password_protects_video_and_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_COUNTER_WEB_TOKEN", "contraseña-de-prueba")
    config = Config(base_dir=tmp_path)
    config.camera.type = "mock"
    runtime = CounterApplication(config)
    client = create_app(runtime).test_client()
    for path in ("/", "/api/status", "/video_feed", "/reports/events.csv", "/reports/summary.csv"):
        assert client.get(path).status_code == 401
    assert client.get("/api/status", auth=("admin", "contraseña-de-prueba")).status_code == 200
    runtime.close()


def test_visitor_settings_persist_without_overwriting_line(web):
    runtime, app, client = web
    headers = {"X-CSRF-Token": app.config["CSRF_TOKEN"]}
    line = {"p1": [0.2, 0.3], "p2": [0.8, 0.3]}
    assert client.post("/api/line", json=line, headers=headers).status_code == 200
    settings = {"enabled": True, "window": "hours", "window_hours": 24}
    result = client.post("/api/visitors", json=settings, headers=headers)
    assert result.status_code == 200
    loaded = load_config(runtime.config.base_dir / "config.yaml")
    assert loaded.visitors.window == "hours" and loaded.visitors.window_hours == 24
    assert loaded.line.p1 == [0.2, 0.3]
    page = client.get("/").text
    assert 'id="unique-visitors"' in page and 'id="visitors-form"' in page
    assert "Sin reconocimiento facial" not in page


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": "true"},
        {"window": "forever"},
        {"window": {}},
        {"window_hours": 0},
        {"window_hours": 169},
        {"window_hours": float("nan")},
        {"key_file": "/tmp/foreign.key"},
    ],
)
def test_invalid_visitor_settings_are_rejected(web, payload):
    _, app, client = web
    headers = {"X-CSRF-Token": app.config["CSRF_TOKEN"]}
    assert client.post("/api/visitors", json=payload, headers=headers).status_code == 400


def test_visitor_actions_require_csrf_and_forgetting_requires_confirmation(web):
    _, app, client = web
    assert client.post("/api/visitors", json={"enabled": False}).status_code == 403
    assert client.post("/api/visitors/forget", json={"confirm": True}).status_code == 403
    headers = {"X-CSRF-Token": app.config["CSRF_TOKEN"]}
    assert client.post("/api/visitors/forget", json={}, headers=headers).status_code == 400
    assert client.post("/api/visitors/forget", json={"confirm": True}, headers=headers).status_code == 200


def test_status_history_and_csv_expose_counts_but_not_templates(web):
    from camera_counter.visitors.store import VisitorStore
    import numpy as np

    runtime, app, client = web
    now = datetime.now(timezone.utc)
    store = VisitorStore(runtime.repository, runtime.config.visitors, runtime.config.base_dir / "key", "test")
    feature = np.eye(1, 128, dtype=np.float32)[0]
    for track in [1, 77]:
        event_id = runtime.repository.record_crossing(
            CrossingEvent(track, "entry", 0.9, "-1->+1", now),
            runtime.session,
            "entrada",
            visitor_enabled=True,
        )
        store.classify(event_id, [feature, feature], now)
    status = client.get("/api/status").json
    assert (status["unique_visitors_today"], status["returning_entries_today"]) == (1, 1)
    history = client.get("/api/history").json
    assert sum(row["unique_visitors"] for row in history) == 1
    csv = client.get("/reports/events.csv").text
    assert "clasificacion_visita" in csv and ",returning," in csv
    assert "template" not in csv and "visitor_id" not in csv and "template" not in str(status)
