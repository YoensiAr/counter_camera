"""Muestreo por track, cruces pendientes y memoria facial acotada."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from camera_counter.database.repository import utc_text
from camera_counter.visitors.store import VisitorStore, normalize

log = logging.getLogger(__name__)


@dataclass
class FaceTrack:
    last_seen: float
    last_attempt: float = float("-inf")
    samples: deque = field(default_factory=lambda: deque(maxlen=5))


@dataclass
class PendingCrossing:
    track_id: int
    deadline: float


class VisitorService:
    def __init__(self, config, repository, *, backend=None):
        self.config = config
        self.repository = repository
        self.backend = backend
        self.store = None
        self.tracks: dict[int, FaceTrack] = {}
        self.pending: dict[int, PendingCrossing] = {}
        self.inference_error = self.comparison_error = ""
        self.started = False
        self.last_cleanup = float("-inf")
        self.last_timestamp = None

    @property
    def enabled(self):
        return self.config.visitors.enabled and self.config.camera.type != "mock"

    def start(self, now=None):
        now = now or datetime.now(timezone.utc)
        self.repository.purge_visitors(now)
        # Un cierre abrupto nunca convierte una entrada sin verificar en visitante nuevo.
        with self.repository.lock, self.repository.connection:
            self.repository.connection.execute(
                "UPDATE visitor_events SET status='unverified',reason='interrupted',resolved_at=? "
                "WHERE status='pending'",
                (utc_text(now),),
            )
        if self.enabled:
            self._load()
        self.started = True

    def _load(self):
        if self.backend is None:
            from camera_counter.visitors.recognizer import FaceRecognizer

            self.backend = FaceRecognizer(self.config)
        if self.store is None:
            self.store = VisitorStore(
                self.repository,
                self.config.visitors,
                self.config.path(self.config.visitors.key_file),
                self.backend.model_id,
            )

    def observe(self, frame, people, timeline: float, timestamp: datetime):
        self.tick(timeline, timestamp)
        if not self.enabled:
            return
        if self.backend is None or self.store is None:
            self._load()
        settings = self.config.visitors
        self.tracks = {
            key: track
            for key, track in self.tracks.items()
            if timeline - track.last_seen <= self.config.tracking.max_lost_seconds
        }
        for person in people:
            if person.observed and (
                person.track_id in self.tracks or len(self.tracks) < self.config.tracking.max_tracks
            ):
                self.tracks.setdefault(person.track_id, FaceTrack(timeline)).last_seen = timeline
        observed = {person.track_id for person in people if person.observed}
        eligible = sorted(
            (
                key
                for key, track in self.tracks.items()
                if key in observed and timeline - track.last_attempt >= settings.sample_interval_seconds
            ),
            key=lambda key: self.tracks[key].last_attempt,
        )[: settings.max_faces_per_frame]
        if not eligible:
            return
        for key in eligible:
            self.tracks[key].last_attempt = timeline
        try:
            features = self.backend.extract(frame, people, set(eligible))
            for track_id, feature in features.items():
                if track_id not in eligible:
                    continue
                vector = normalize(feature)
                track = self.tracks[track_id]
                self._prune_samples(track, timeline)
                if any(float(vector @ sample) < settings.match_threshold for _, sample in track.samples):
                    track.samples.clear()
                track.samples.append((timeline, vector.copy()))
            self.inference_error = ""
        except Exception as exc:
            message = "No se pudo verificar el rostro: " + str(exc)
            if message != self.inference_error:
                log.error("%s", message)
            self.inference_error = message
            # No reutilizar una cara anterior tras un fallo de inferencia.
            for key in eligible:
                self.tracks[key].samples.clear()

    def record(self, event, session: str, timeline: float):
        event_id = self.repository.record_crossing(
            event,
            session,
            self.config.camera.name,
            visitor_enabled=self.enabled,
        )
        if event_id is not None and self.enabled:
            if len(self.pending) >= self.config.tracking.max_tracks:
                self._unverified(event_id, "pending_capacity", event.timestamp)
            else:
                self.pending[event_id] = PendingCrossing(event.track_id, timeline + self.config.visitors.pending_seconds)
        return event_id is not None

    def _prune_samples(self, track, timeline):
        while track.samples and timeline - track.samples[0][0] > self.config.visitors.sample_ttl_seconds:
            track.samples.popleft()

    def flush(self, timeline: float, timestamp: datetime):
        for event_id, crossing in list(self.pending.items()):
            if timeline >= crossing.deadline:
                self._unverified(event_id, "no_usable_face", timestamp)
                del self.pending[event_id]
                continue
            track = self.tracks.get(crossing.track_id)
            if track:
                self._prune_samples(track, timeline)
            if track is None or len(track.samples) < self.config.visitors.min_samples:
                continue
            try:
                self.store.classify(event_id, [sample for _, sample in track.samples], timestamp)
                self.comparison_error = ""
            except Exception as exc:
                message = "No se pudo comparar la referencia facial: " + str(exc)
                if message != self.comparison_error:
                    log.error("%s", message)
                self.comparison_error = message
                self._unverified(event_id, "recognition_error", timestamp)
            del self.pending[event_id]

    def tick(self, timeline: float, timestamp: datetime):
        self.last_timestamp = timestamp
        self.tracks = {
            key: track
            for key, track in self.tracks.items()
            if timeline - track.last_seen <= self.config.tracking.max_lost_seconds
        }
        for track in self.tracks.values():
            self._prune_samples(track, timeline)
        if timeline - self.last_cleanup >= 30 or timeline < self.last_cleanup:
            self.repository.purge_visitors(timestamp)
            self.last_cleanup = timeline

    def _unverified(self, event_id, reason, timestamp):
        with self.repository.lock, self.repository.connection:
            self.repository.connection.execute(
                "UPDATE visitor_events SET status='unverified',reason=?,resolved_at=? WHERE event_id=? AND status='pending'",
                (reason, utc_text(timestamp), event_id),
            )

    def finish(self, reason="stopped", timestamp=None):
        now = timestamp or self.last_timestamp or datetime.now(timezone.utc)
        for event_id in self.pending:
            self._unverified(event_id, reason, now)
        self.pending.clear()
        self.tracks.clear()

    def forget(self):
        self.finish("forgotten")
        with self.repository.lock, self.repository.connection:
            self.repository.connection.execute("DELETE FROM visitors")
        self.repository.checkpoint()

    def reconfigure(self, settings, now=None):
        settings.validate()
        now = now or datetime.now(timezone.utc)
        if settings.enabled and self.config.camera.type != "mock":
            self._load()
        self.finish("configuration_changed", now)
        if self.store:
            self.store.set_window(settings, now)
        self.config.visitors = settings
        if self.backend is not None and hasattr(self.backend, "settings"):
            self.backend.settings = settings

    def status(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self.repository.lock:
            active = self.repository.connection.execute(
                "SELECT COUNT(*) FROM visitors WHERE expires_at>?",
                (utc_text(now),),
            ).fetchone()[0]
        return {
            "enabled": self.config.visitors.enabled,
            "active": self.enabled and self.store is not None,
            "mode": "simulation" if self.config.camera.type == "mock" else ("face" if self.enabled else "disabled"),
            "window": self.config.visitors.window,
            "window_hours": self.config.visitors.window_hours,
            "active_references": active,
            "error": self.comparison_error or self.inference_error,
        }
