"""Confirma cruces físicos; la identidad y sus reingresos se resuelven aparte."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

from camera_counter.config import LineConfig
from camera_counter.counting.geometry import CountingLine
from camera_counter.counting.track_state import PersonState, TrackMemory
from camera_counter.types import CrossingEvent, TrackedPerson

log = logging.getLogger(__name__)


class LineCounter:
    def __init__(
        self, config: LineConfig, width: int, height: int, max_lost_seconds: float = 2.5, max_tracks: int = 512
    ):
        config.validate()
        self.config = config
        self.width, self.height = width, height
        self.max_lost_seconds = max_lost_seconds
        self.max_tracks = max_tracks
        self.tracks: dict[int, TrackMemory] = {}
        self.line = self._geometry()
        self.crossing_sequence = 0
        self.lost_inside = set()

    def invalidate(self, track_ids):
        """Olvida el trayecto dudoso conservando la secuencia de eventos de la sesión."""
        uncertain = False
        for key in track_ids:
            memory = self.tracks.get(key)
            if memory is not None:
                uncertain |= memory.stable_side == self._inside_side and "entry" in memory.counted
                memory.history.clear()
                memory.confidences.clear()
                memory.previous_position = None
                memory.stable_side = memory.candidate_side = memory.confirmations = 0
                memory.intersected = False
                memory.state = PersonState.UNKNOWN
        return uncertain

    def _geometry(self) -> CountingLine:
        return CountingLine(
            (self.config.p1[0] * self.width, self.config.p1[1] * self.height),
            (self.config.p2[0] * self.width, self.config.p2[1] * self.height),
            self.config.margin_px,
        )

    def reconfigure(self, config: LineConfig, width: int, height: int) -> None:
        """Cambiar la línea nunca crea un cruce; se conserva la deduplicación."""
        config.validate()
        self.config, self.width, self.height = config, width, height
        self.line = self._geometry()
        for track in self.tracks.values():
            track.history = deque(maxlen=config.history_size)
            track.confidences = deque(maxlen=config.history_size)
            track.previous_position = None
            track.stable_side = track.candidate_side = track.confirmations = 0
            track.intersected = False
            track.state = PersonState.UNKNOWN

    def expire(self, now: float) -> None:
        self.lost_inside.update(
            key for key, memory in self.tracks.items()
            if now - memory.last_seen > self.max_lost_seconds and memory.stable_side == self._inside_side and "entry" in memory.counted
        )
        # El consumidor drena esta señal por frame; también se acota para usos autónomos.
        self.lost_inside = set(sorted(self.lost_inside)[-self.max_tracks:])
        self.tracks = {
            key: value for key, value in self.tracks.items() if now - value.last_seen <= self.max_lost_seconds
        }

    def update(self, people: list[TrackedPerson], now: float, timestamp: datetime) -> list[CrossingEvent]:
        self.expire(now)
        observed = {}
        for person in people:
            if not person.observed:
                continue
            x, y = self.anchor(person)
            roi = self.config.roi
            if roi is not None and not (roi[0] <= x / self.width <= roi[2] and roi[1] <= y / self.height <= roi[3]):
                self.invalidate([person.track_id])
                continue
            observed[person.track_id] = person
        for key, memory in self.tracks.items():
            if key not in observed:
                memory.confirmations = 0
                memory.candidate_side = 0
        events = []
        for key, person in observed.items():
            if key not in self.tracks:
                if len(self.tracks) >= self.max_tracks:
                    log.warning("Límite de tracks alcanzado; se omite un track nuevo.")
                    continue
                self.tracks[key] = TrackMemory(
                    now, now, deque(maxlen=self.config.history_size), deque(maxlen=self.config.history_size)
                )
            memory = self.tracks[key]
            current = self.anchor(person)
            memory.previous_position = memory.history[-1] if memory.history else None
            if memory.previous_position is not None and memory.stable_side:
                memory.intersected |= self.line.intersects(memory.previous_position, current)
            memory.history.append(current)
            memory.confidences.append(person.confidence)
            memory.last_seen = now
            side = self.line.side(current)
            if side == 0:
                memory.confirmations = 0
                memory.candidate_side = 0
                if memory.stable_side:
                    memory.state = PersonState.CROSSING
                continue
            if side == memory.candidate_side:
                memory.confirmations += 1
            else:
                memory.candidate_side, memory.confirmations = side, 1
            if side == memory.stable_side:
                memory.intersected = False
                memory.state = self._stable_state(side, memory)
                continue
            if memory.stable_side:
                memory.state = PersonState.CROSSING
            if memory.confirmations < self.config.confirmation_frames:
                continue
            previous_side = memory.stable_side
            memory.stable_side = side
            event_type = "entry" if side == self._inside_side else "exit"
            memory.direction = f"{previous_side:+d}->{side:+d}"
            valid = previous_side and memory.intersected
            # Un retorno confirmado es otro cruce físico, aunque sea inmediato.
            # Bloquearlo aquí cambiaba el lado estable sin registrar la salida,
            # dejando ocupación y seguimiento en desacuerdo de forma permanente.
            repeated_direction = event_type == memory.last_event_type
            if valid and (not repeated_direction or now - memory.last_event_at >= self.config.cooldown_seconds):
                memory.counted.add(event_type)
                memory.last_event_at = now
                memory.last_event_type = event_type
                self.crossing_sequence += 1
                memory.crossing_index = self.crossing_sequence
                events.append(
                    CrossingEvent(
                        key,
                        event_type,
                        sum(memory.confidences) / len(memory.confidences),
                        memory.direction,
                        timestamp,
                        memory.crossing_index,
                    )
                )
            memory.intersected = False
            memory.state = self._stable_state(side, memory)
        return events

    def anchor(self, person):
        x1, y1, x2, y2 = person.box
        fraction = {"center": .5, "feet": 1.0, "head": .15}[self.config.anchor]
        return ((x1 + x2) / 2, y1 + (y2 - y1) * fraction)

    @property
    def _inside_side(self) -> int:
        return 1 if self.config.entry_to == "positive" else -1

    def _stable_state(self, side: int, memory: TrackMemory) -> PersonState:
        if side == self._inside_side:
            return PersonState.COUNTED_ENTRY if "entry" in memory.counted else PersonState.INSIDE
        return PersonState.COUNTED_EXIT if "exit" in memory.counted else PersonState.OUTSIDE
