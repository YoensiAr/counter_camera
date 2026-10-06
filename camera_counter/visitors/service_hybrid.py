"""Seguimiento observado + rostro + OSNet. Una identidad no ocupa dos tracks visibles."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math

from camera_counter.visitors.body import BodyRecognizer, body_vector, crowded_tracks
from camera_counter.visitors.hybrid import HybridStore
from camera_counter.visitors.service import FaceTrack, VisitorService, log
from camera_counter.visitors.store import normalize


@dataclass
class HybridTrack(FaceTrack):
    bodies: deque = field(default_factory=lambda: deque(maxlen=8))
    last_box: tuple | None = None
    identity: str | None = None
    evidence: str = ""
    last_evidence: float = float("-inf")
    generation: int = 0
    crowded: bool = False
    learn_body: bool = False
    reason: str = "insufficient_evidence"
    uncertain_identity: bool = False


@dataclass
class HybridPending:
    track_id: int
    deadline: float
    generation: int


class HybridVisitorService(VisitorService):
    def __init__(self, config, repository, *, backend=None, body_backend=None):
        super().__init__(config, repository, backend=backend)
        self.body_backend = body_backend
        self.body_error = ""
        self.invalidated_tracks = set()
        self._generation = 0
        self._timeline = None
        self._visible = set()

    @property
    def hybrid(self):
        return self.config.visitors.mode == "hybrid"

    def _load(self):
        if not self.hybrid:
            return super()._load()
        if self.backend is None:
            from camera_counter.visitors.recognizer import FaceRecognizer
            self.backend = FaceRecognizer(self.config)
        if self.body_backend is None:
            self.body_backend = BodyRecognizer(self.config)
        if self.store is None:
            self.store = HybridStore(
                self.repository, self.config.visitors, self.config.path(self.config.visitors.key_file),
                self.backend.model_id, self.body_backend.model_id,
            )

    def _invalidate(self, track_id, reason, timestamp):
        track = self.tracks.get(track_id)
        if not isinstance(track, HybridTrack):
            return
        self._generation += 1
        track.generation = self._generation
        track.uncertain_identity |= track.identity is not None
        track.identity, track.evidence, track.learn_body = None, "", False
        track.last_evidence = float("-inf")
        track.samples.clear()
        track.bodies.clear()
        track.reason = reason
        self.invalidated_tracks.add(track_id)
        for event_id, pending in list(self.pending.items()):
            if pending.track_id == track_id:
                self._unverified(event_id, reason, timestamp)
                del self.pending[event_id]

    def take_invalidated_tracks(self):
        result = self.invalidated_tracks
        self.invalidated_tracks = set()
        return result

    def _hint(self, track, timeline):
        cfg = self.config.visitors
        if (not track.crowded and timeline - track.last_seen <= cfg.continuity_gap_seconds
                and timeline - track.last_evidence <= cfg.continuity_evidence_seconds):
            return track.identity
        return None

    def _excluded(self, track_id, timeline):
        return {
            t.identity for key, t in self.tracks.items()
            if key != track_id and key in self._visible and self._hint(t, timeline)
        }

    def observe(self, frame, people, timeline, timestamp):
        if not self.hybrid:
            return super().observe(frame, people, timeline, timestamp)
        self.tick(timeline, timestamp)
        if not self.enabled:
            return
        self._load()
        cfg = self.config.visitors
        observed = [p for p in people if p.observed and all(math.isfinite(v) for v in p.box)]
        self._visible = {p.track_id for p in observed}
        crowded = crowded_tracks(observed, cfg.body_max_overlap)
        for person in observed:
            key = person.track_id
            if key not in self.tracks:
                if len(self.tracks) >= self.config.tracking.max_tracks:
                    continue
                self._generation += 1
                self.tracks[key] = HybridTrack(last_seen=timeline, generation=self._generation)
            track = self.tracks[key]
            gap = timeline - track.last_seen
            if track.last_box is not None:
                box = track.last_box
                previous = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                scale = max(1.0, min(box[3] - box[1], person.box[3] - person.box[1]))
                if gap > cfg.continuity_gap_seconds or math.dist(previous, person.center) > scale * (.25 + cfg.continuity_speed * max(0, gap)):
                    self._invalidate(key, "track_discontinuity", timestamp)
            if key in crowded and not track.crowded:
                self._invalidate(key, "overlapping_people", timestamp)
            track.crowded = key in crowded
            track.last_seen, track.last_box = timeline, person.box
        eligible = sorted(
            (key for key in self._visible if key in self.tracks and not self.tracks[key].crowded
             and timeline - self.tracks[key].last_attempt >= cfg.sample_interval_seconds),
            key=lambda key: self.tracks[key].last_attempt,
        )[:cfg.max_faces_per_frame]
        if not eligible:
            return
        for key in eligible:
            self.tracks[key].last_attempt = timeline
        faces, bodies = {}, {}
        try:
            faces = self.backend.extract(frame, people, set(eligible))
            self.inference_error = ""
        except Exception as exc:
            self.inference_error = "Falló la verificación facial: " + str(exc)
            for key in eligible:
                self.tracks[key].samples.clear()
        try:
            bodies = self.body_backend.extract(frame, people, set(eligible))
            self.body_error = ""
        except Exception as exc:
            self.body_error = "Falló la comparación corporal: " + str(exc)
            for key in eligible:
                self._invalidate(key, "body_backend_error", timestamp)
        for key in eligible:
            track = self.tracks[key]
            try:
                if key in faces:
                    vector = normalize(faces[key])
                    if any(float(vector @ old) < cfg.match_threshold for _, old in track.samples):
                        # Un perfil borroso aislado no debe borrar un trayecto corporal válido.
                        # Reunir otra vez muestras coherentes antes de decidir si cambió la cara.
                        track.samples.clear()
                    track.samples.append((timeline, vector.copy()))
                if key in bodies:
                    vector = body_vector(bodies[key])
                    if track.bodies and float(vector @ track.bodies[-1][1]) < cfg.body_new_threshold:
                        self._invalidate(key, "appearance_changed_on_track", timestamp)
                    while track.bodies and any(float(vector @ old) < cfg.body_consistency_threshold for _, old in track.bodies):
                        track.bodies.popleft()
                    track.bodies.append((timeline, vector.copy()))
                if key in faces or key in bodies:
                    self._resolve_track(key, timeline, timestamp)
            except Exception as exc:
                message = "No se pudo resolver la identidad temporal: " + str(exc)
                if message != self.comparison_error:
                    log.error("%s", message)
                self.comparison_error = message
                self._invalidate(key, "identity_error", timestamp)

    def _resolve_track(self, key, timeline, timestamp):
        track = self.tracks[key]
        faces = [sample for _, sample in track.samples]
        bodies = [sample for _, sample in track.bodies]
        hint = self._hint(track, timeline)
        decision = self.store.match(faces, bodies, timestamp, hint=hint, excluded=self._excluded(key, timeline))
        track.reason = decision.reason
        if decision.kind == "conflict":
            self._invalidate(key, decision.reason, timestamp)
        elif decision.kind == "match":
            same = track.identity == decision.visitor_id
            track.identity, track.evidence = decision.visitor_id, decision.evidence
            track.uncertain_identity = False
            # Una pista de movimiento no se renueva sola: se necesita imagen corporal/cara reciente.
            if decision.evidence != "continuity" or len(bodies) >= self.config.visitors.body_min_samples or len(faces) >= self.config.visitors.min_samples:
                track.last_evidence = timeline
            if decision.evidence == "face":
                track.learn_body = True
            elif not same:
                track.learn_body = False
            self.store.remember(track.identity, faces, bodies, timestamp, learn_body=track.learn_body)
        elif hint is None:
            track.identity, track.evidence, track.learn_body = None, "", False
        self.comparison_error = ""

    def record(self, event, session, timeline):
        if not self.hybrid:
            return super().record(event, session, timeline)
        event_id = self.repository.record_crossing(event, session, self.config.camera.name, visitor_enabled=self.enabled)
        if event_id is not None and self.enabled:
            track = self.tracks.get(event.track_id)
            if track is None or track.crowded:
                self._unverified(event_id, "no_observed_track", event.timestamp)
            elif len(self.pending) >= self.config.tracking.max_tracks:
                self._unverified(event_id, "pending_capacity", event.timestamp)
            else:
                self.pending[event_id] = HybridPending(event.track_id, timeline + self.config.visitors.pending_seconds, track.generation)
        return event_id is not None

    def flush(self, timeline, timestamp):
        if not self.hybrid:
            return super().flush(timeline, timestamp)
        for event_id, pending in list(self.pending.items()):
            track = self.tracks.get(pending.track_id)
            if track is None or track.generation != pending.generation or track.crowded:
                self._unverified(event_id, "track_discontinuity", timestamp)
                del self.pending[event_id]
                continue
            self._prune_samples(track, timeline)
            if timeline >= pending.deadline:
                self._unverified(event_id, track.reason or "insufficient_evidence", timestamp)
                del self.pending[event_id]
                continue
            try:
                result = self.store.classify(
                    event_id, [sample for _, sample in track.samples], timestamp,
                    body_samples=[sample for _, sample in track.bodies], hint=self._hint(track, timeline),
                    excluded=self._excluded(pending.track_id, timeline),
                    allow_new=not track.uncertain_identity,
                )
                self.comparison_error = ""
                if result == "pending":
                    continue
                identity, evidence = self.store.event_identity(event_id)
                if identity:
                    same = track.identity == identity
                    track.identity, track.evidence, track.last_evidence = identity, evidence, timeline
                    track.learn_body = track.learn_body if same else (result == "new" or evidence == "face")
                    self.store.remember(identity, [s for _, s in track.samples], [s for _, s in track.bodies], timestamp, learn_body=track.learn_body)
            except Exception as exc:
                self.comparison_error = "No se pudo guardar la identidad temporal: " + str(exc)
                log.error("%s", self.comparison_error)
                self._unverified(event_id, "recognition_error", timestamp)
            del self.pending[event_id]

    def _prune_samples(self, track, timeline):
        super()._prune_samples(track, timeline)
        if isinstance(track, HybridTrack):
            while track.bodies and timeline - track.bodies[0][0] > self.config.visitors.sample_ttl_seconds:
                track.bodies.popleft()

    def tick(self, timeline, timestamp):
        if not self.hybrid:
            return super().tick(timeline, timestamp)
        if self._timeline is not None and timeline < self._timeline:
            for key in list(self.tracks):
                self._invalidate(key, "timeline_rewound", timestamp)
            self.tracks.clear()
        self._timeline = timeline
        for key, track in list(self.tracks.items()):
            if timeline - track.last_seen > self.config.tracking.max_lost_seconds:
                self._invalidate(key, "track_expired", timestamp)
        cleanup = timeline - self.last_cleanup >= 30 or timeline < self.last_cleanup
        super().tick(timeline, timestamp)
        if cleanup and isinstance(self.store, HybridStore):
            self.store.clear_cache()

    def finish(self, reason="stopped", timestamp=None):
        super().finish(reason, timestamp)
        self._visible.clear()
        self._timeline = None
        if isinstance(self.store, HybridStore):
            self.store.clear_cache()

    def reconfigure(self, settings, now=None):
        super().reconfigure(settings, now)
        if self.body_backend is not None and hasattr(self.body_backend, "settings"):
            self.body_backend.settings = settings

    def track_labels(self):
        if not self.hybrid:
            return {}
        labels = {"face": "rostro", "body": "cuerpo", "continuity": "seguimiento"}
        return {
            key: labels.get(track.evidence, "sin verificar") if self._hint(track, self._timeline or 0) else "sin verificar"
            for key, track in self.tracks.items()
        }

    def status(self, now=None):
        result = super().status(now)
        if self.hybrid and result["mode"] == "face":
            result["mode"] = "hybrid"
        result["body_model"] = "OSNet x0.25 / CPU" if self.body_backend else ""
        result["error"] = self.comparison_error or self.body_error or self.inference_error
        result["method"] = self.config.visitors.mode
        return result
