"""Galería cifrada: una entrada y una salida por referencia vigente, sin fotografías."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

from camera_counter.config import VisitorsConfig
from camera_counter.database.repository import utc_text


def normalize(value) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    if vector.shape != (128,) or not np.isfinite(vector).all():
        raise ValueError("La referencia facial debe contener 128 valores finitos.")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-8:
        raise ValueError("La referencia facial está vacía.")
    return vector / norm


def expires_at(created: datetime, config: VisitorsConfig, zone) -> datetime:
    if created.tzinfo is None:
        raise ValueError("La fecha requiere zona horaria.")
    if config.window == "hours":
        return created.astimezone(timezone.utc) + timedelta(hours=config.window_hours)
    tomorrow = created.astimezone(zone).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=zone).astimezone(timezone.utc)


class VisitorStore:
    def __init__(self, repository, config: VisitorsConfig, key_path: Path, model_id: str):
        self.repository = repository
        self.config = config
        self.model_id = model_id
        self.cipher = self._cipher(key_path)
        with repository.lock:
            incompatible = repository.connection.execute(
                "SELECT COUNT(*) FROM visitors WHERE face_ready=1 AND model_id!=?",
                (model_id,),
            ).fetchone()[0]
        if incompatible:
            raise RuntimeError(
                "Las referencias guardadas pertenecen a otro modelo facial. Restaura el modelo original "
                "o espera a que caduquen; no se contarán automáticamente como personas nuevas."
            )

    def _cipher(self, path: Path) -> Fernet:
        if self.repository.is_memory:
            return Fernet(Fernet.generate_key())
        if not path.exists():
            with self.repository.lock:
                existing = self.repository.connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]
            if existing:
                raise RuntimeError(
                    "Falta la clave de visitantes. Restaura data/visitors.key junto con la base de datos."
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(Fernet.generate_key())
                    output.flush()
                    os.fsync(output.fileno())
        try:
            cipher = Fernet(path.read_bytes().strip())
        except (ValueError, OSError) as exc:
            raise RuntimeError("No se puede leer la clave de visitantes; no se reemplazará automáticamente.") from exc
        # Un cambio de clave no debe convertir referencias existentes en visitantes nuevos.
        with self.repository.lock:
            row = self.repository.connection.execute("SELECT template FROM visitors LIMIT 1").fetchone()
        if row:
            try:
                cipher.decrypt(row[0])
            except InvalidToken as exc:
                raise RuntimeError(
                    "La clave no corresponde a los visitantes guardados. Restaura la clave original."
                ) from exc
        return cipher

    def classify(self, event_id: int, samples: list[np.ndarray], now: datetime) -> str:
        if len(samples) < self.config.min_samples:
            raise ValueError("No hay suficientes muestras faciales.")
        vectors = [normalize(sample) for sample in samples]
        # Exige coherencia entre TODAS las muestras, evitando unir dos caras por un cambio de ID.
        if any(float(a @ b) < self.config.match_threshold for i, a in enumerate(vectors) for b in vectors[i + 1 :]):
            return self.unverified(event_id, "inconsistent_samples", now)
        feature = normalize(np.mean(vectors, axis=0))
        repository = self.repository
        with repository.lock, repository.connection:
            # Serializa comparación + alta incluso con más de una conexión SQLite.
            repository.connection.execute("BEGIN IMMEDIATE")
            event = repository.connection.execute(
                "SELECT e.timestamp,e.event_type,v.status FROM events e JOIN visitor_events v ON v.event_id=e.id WHERE e.id=?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise ValueError("El cruce no existe.")
            if event["status"] != "pending":
                return event["status"]
            created = datetime.fromisoformat(event["timestamp"])
            expiry = expires_at(created, self.config, repository.zone)
            if now >= expiry:
                return self._resolve(event_id, "unverified", "window_expired", now)
            rows = repository.connection.execute(
                "SELECT id,template FROM visitors WHERE face_ready=1 AND model_id=? AND expires_at>?",
                (self.model_id, utc_text(now)),
            ).fetchall()
            ranked = []
            for row in rows:
                try:
                    raw = self.cipher.decrypt(row["template"])
                    saved = normalize(np.frombuffer(raw, dtype="<f4"))
                except (InvalidToken, ValueError) as exc:
                    raise RuntimeError("Una referencia facial no se puede leer; revisa la base y su clave.") from exc
                ranked.append((float(feature @ saved), row["id"]))
            ranked.sort(reverse=True)
            best, visitor_id = ranked[0] if ranked else (-1.0, None)
            second = ranked[1][0] if len(ranked) > 1 else -1.0
            if best >= self.config.match_threshold:
                if best - second < self.config.ambiguity_margin:
                    return self._resolve(event_id, "unverified", "ambiguous_match", now, similarity=best)
                # No prolongar la caducidad al regresar y no adaptar la plantilla (evita deriva).
                return self._count_direction(event_id, event["event_type"], visitor_id, now, best)
            if ranked and best > self.config.new_threshold:
                return self._resolve(event_id, "unverified", "uncertain_match", now, similarity=best)
            if repository.connection.execute("SELECT 1 FROM visitors WHERE face_ready=0 AND expires_at>? LIMIT 1", (utc_text(now),)).fetchone():
                return self._resolve(event_id, "unverified", "body_reference_requires_hybrid", now)
            count = repository.connection.execute(
                "SELECT COUNT(*) FROM visitors WHERE expires_at>?", (utc_text(now),)
            ).fetchone()[0]
            if count >= self.config.max_identities:
                return self._resolve(event_id, "unverified", "capacity", now)
            visitor_id = uuid.uuid4().hex
            repository.connection.execute(
                "INSERT INTO visitors(id,model_id,template,created_at,expires_at) VALUES(?,?,?,?,?)",
                (
                    visitor_id,
                    self.model_id,
                    self.cipher.encrypt(feature.astype("<f4").tobytes()),
                    utc_text(created),
                    utc_text(expiry),
                ),
            )
            return self._count_direction(event_id, event["event_type"], visitor_id, now)

    def _count_direction(self, event_id, direction, visitor_id, now, similarity=None, *, evidence="face"):
        column = {"entry": "entry_counted", "exit": "exit_counted"}[direction]
        # Bandera y decisión comparten la transacción de classify: un reinicio,
        # otro ID o dos conexiones concurrentes no pueden sumar la misma dirección.
        changed = self.repository.connection.execute(
            f"UPDATE visitors SET {column}=1 WHERE id=? AND {column}=0", (visitor_id,)
        ).rowcount
        return self._resolve(
            event_id,
            "new" if changed else "returning",
            f"first_{direction}" if changed else evidence + "_match",
            now,
            visitor_id,
            similarity,
            counted=bool(changed),
            evidence=evidence,
        )

    def _resolve(self, event_id, status, reason, now, visitor_id=None, similarity=None, *, counted=False, evidence=""):
        self.repository.connection.execute(
            "UPDATE visitor_events SET status=?,reason=?,resolved_at=?,visitor_id=?,similarity=?,counted=?,evidence=? "
            "WHERE event_id=? AND status='pending'",
            (status, reason, utc_text(now), visitor_id, similarity, int(counted), evidence, event_id),
        )
        return status

    def unverified(self, event_id: int, reason: str, now: datetime) -> str:
        with self.repository.lock, self.repository.connection:
            row = self.repository.connection.execute(
                "SELECT status FROM visitor_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise ValueError("El cruce no existe.")
            if row[0] != "pending":
                return row[0]
            return self._resolve(event_id, "unverified", reason, now)

    def set_window(self, config: VisitorsConfig, now: datetime) -> None:
        config.validate()
        self.repository.purge_visitors(now)
        with self.repository.lock, self.repository.connection:
            rows = self.repository.connection.execute("SELECT id,created_at FROM visitors").fetchall()
            self.repository.connection.executemany(
                "UPDATE visitors SET expires_at=? WHERE id=?",
                [
                    (
                        utc_text(expires_at(datetime.fromisoformat(row["created_at"]), config, self.repository.zone)),
                        row["id"],
                    )
                    for row in rows
                ],
            )
        self.config = config
        self.repository.purge_visitors(now)
