"""Cada evento y sus totales se confirman en la misma transacción."""

import logging
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from camera_counter.database.models import EVENTS_SCHEMA, SCHEMA
from camera_counter.types import CrossingEvent

log = logging.getLogger(__name__)


def utc_text(timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Repository:
    def __init__(self, path: str | Path, timezone_name: str = "America/Santo_Domingo"):
        self.is_memory = str(path) == ":memory:"
        self.path = Path(path) if not self.is_memory else None
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.zone = ZoneInfo(timezone_name)
        self.connection = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.execute("PRAGMA secure_delete=ON")
        self._migrate_events()
        self.connection.executescript(SCHEMA)
        self._migrate_visitor_counts()
        self._migrate_hybrid()
        self.closed = False
        self.active_sessions: set[str] = set()

    def _migrate_hybrid(self):
        additions = []
        for table, column, declaration in (
            ("visitors", "face_ready", "INTEGER NOT NULL DEFAULT 1 CHECK(face_ready IN (0,1))"),
            ("visitor_events", "evidence", "TEXT NOT NULL DEFAULT ''"),
            ("counters", "uncertain", "INTEGER NOT NULL DEFAULT 0 CHECK(uncertain IN (0,1))"),
            ("counters", "uncertainty_reason", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}:
                additions.append((table, column, declaration))
        if not additions:
            return
        if self.path is not None:
            backup = self.path.with_name(self.path.name + ".before-hybrid-v3.bak")
            if not backup.exists():
                destination = sqlite3.connect(str(backup))
                try:
                    self.connection.backup(destination)
                finally:
                    destination.close()
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            for table, column, declaration in additions:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            self.connection.execute("UPDATE visitor_events SET evidence='face' WHERE status IN ('new','returning') AND evidence=''")

    def _migrate_events(self) -> None:
        """Conserva IDs, historial y totales de la versión sin reingresos."""
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(events)")}
        if not columns or "crossing_index" in columns:
            return
        if self.path is not None:
            backup = self.path.with_name(self.path.name + ".before-visitors-v2.bak")
            if not backup.exists():
                destination = sqlite3.connect(str(backup))
                try:
                    self.connection.backup(destination)
                finally:
                    destination.close()
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(EVENTS_SCHEMA.replace("events (", "events_v2 ("))
            self.connection.execute(
                "INSERT INTO events_v2(id,timestamp,local_day,local_hour,event_type,track_id,source,"
                "confidence,direction,session_id) SELECT id,timestamp,local_day,local_hour,event_type,"
                "track_id,source,confidence,direction,session_id FROM events"
            )
            self.connection.execute("DROP TABLE events")
            self.connection.execute("ALTER TABLE events_v2 RENAME TO events")

    def _migrate_visitor_counts(self) -> None:
        """v2.1: conserva cruces y deduplica ambas direcciones de cada referencia."""
        visitor_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(visitors)")}
        event_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(visitor_events)")}
        missing = self.connection.execute(
            "SELECT 1 FROM events e LEFT JOIN visitor_events v ON v.event_id=e.id "
            "WHERE v.event_id IS NULL LIMIT 1"
        ).fetchone()
        if {"entry_counted", "exit_counted"} <= visitor_columns and "counted" in event_columns and not missing:
            return
        if self.path is not None:
            backup = self.path.with_name(self.path.name + ".before-direction-counts-v2.1.bak")
            if not backup.exists():
                destination = sqlite3.connect(str(backup))
                try:
                    self.connection.backup(destination)
                finally:
                    destination.close()
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            for direction in ("entry", "exit"):
                if f"{direction}_counted" not in visitor_columns:
                    self.connection.execute(
                        f"ALTER TABLE visitors ADD COLUMN {direction}_counted INTEGER NOT NULL DEFAULT 0 "
                        f"CHECK({direction}_counted IN (0,1))"
                    )
                    if direction == "entry":
                        # v2 solo creaba referencias al verificar una primera entrada.
                        self.connection.execute("UPDATE visitors SET entry_counted=1")
            if "counted" not in event_columns:
                self.connection.execute(
                    "ALTER TABLE visitor_events ADD COLUMN counted INTEGER NOT NULL DEFAULT 0 CHECK(counted IN (0,1))"
                )
                self.connection.execute("UPDATE visitor_events SET counted=(status IN ('new','disabled'))")
            # v2 no verificaba salidas: no se puede deducir a qué rostro pertenecían.
            # Los eventos de sesiones sin reconocimiento conservan su conteo físico.
            self.connection.execute(
                "WITH facial_sessions AS (SELECT DISTINCT e.session_id FROM events e "
                "JOIN visitor_events v ON v.event_id=e.id WHERE v.status!='disabled') "
                "INSERT INTO visitor_events(event_id,status,reason,counted) "
                "SELECT e.id, CASE WHEN f.session_id IS NULL THEN 'disabled' ELSE 'unverified' END, "
                "CASE WHEN f.session_id IS NULL THEN 'legacy_crossing' ELSE 'legacy_unverified' END, "
                "f.session_id IS NULL FROM events e LEFT JOIN visitor_events v ON v.event_id=e.id "
                "LEFT JOIN facial_sessions f ON f.session_id=e.session_id WHERE v.event_id IS NULL"
            )

    def start_session(self, source: str, now: datetime | None = None) -> str:
        session = uuid.uuid4().hex
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO sessions(id,started_at,source) VALUES(?,?,?)",
                (session, utc_text(now or datetime.now(timezone.utc)), source),
            )
            self.active_sessions.add(session)
        return session

    def end_session(self, session: str) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE sessions SET ended_at=? WHERE id=?", (utc_text(datetime.now(timezone.utc)), session)
            )
            self.active_sessions.discard(session)

    def record(self, event: CrossingEvent, session: str, source: str) -> bool:
        return self.record_crossing(event, session, source) is not None

    def record_crossing(
        self, event: CrossingEvent, session: str, source: str, *, visitor_enabled: bool = False
    ) -> int | None:
        local = event.timestamp.astimezone(self.zone)
        with self.lock, self.connection:
            cursor = self.connection.execute(
                "INSERT INTO events(timestamp,local_day,local_hour,event_type,track_id,source,"
                "confidence,direction,session_id,crossing_index) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id,track_id,event_type,crossing_index) DO NOTHING",
                (
                    utc_text(event.timestamp),
                    local.date().isoformat(),
                    local.replace(minute=0, second=0, microsecond=0).isoformat(),
                    event.event_type,
                    event.track_id,
                    source,
                    event.confidence,
                    event.direction,
                    session,
                    event.crossing_index,
                ),
            )
            if cursor.rowcount == 0:
                return None
            self.connection.execute(
                "INSERT INTO visitor_events(event_id,status,counted) VALUES(?,?,?)",
                (cursor.lastrowid, "pending" if visitor_enabled else "disabled", int(not visitor_enabled)),
            )
            if event.event_type == "entry":
                self.connection.execute("UPDATE counters SET entries=entries+1 WHERE singleton=1")
            else:
                self.connection.execute("UPDATE counters SET exits=exits+1 WHERE singleton=1")
                row = self.connection.execute("SELECT entries,exits FROM counters WHERE singleton=1").fetchone()
                if row["exits"] > row["entries"]:
                    log.warning(
                        "Ocupación inconsistente: %s entradas y %s salidas. Se muestra cero.",
                        row["entries"],
                        row["exits"],
                    )
        return cursor.lastrowid

    def stats(self, now: datetime | None = None) -> dict:
        local_day = (now or datetime.now(timezone.utc)).astimezone(self.zone).date().isoformat()
        with self.lock:
            totals = self.connection.execute("SELECT * FROM counters WHERE singleton=1").fetchone()
            day = self.connection.execute(
                "SELECT COALESCE(SUM(event_type='entry'),0) AS entries, "
                "COALESCE(SUM(event_type='exit'),0) AS exits FROM events WHERE local_day=? AND id>?",
                (local_day, totals["reset_event_id"]),
            ).fetchone()
            visitors = self.connection.execute(
                "SELECT COALESCE(SUM(v.status='new'),0) AS unique_visitors_today, "
                "COALESCE(SUM(v.status='returning'),0) AS returning_entries_today, "
                "COALESCE(SUM(v.status='unverified'),0) AS unverified_entries_today, "
                "COALESCE(SUM(v.status='pending'),0) AS pending_entries_today, "
                "COALESCE(SUM(v.status='disabled' OR v.status IS NULL),0) AS unchecked_entries_today "
                "FROM events e LEFT JOIN visitor_events v ON e.id=v.event_id "
                "WHERE e.local_day=? AND e.event_type='entry'",
                (local_day,),
            ).fetchone()
            directions = self.connection.execute(
                "SELECT COALESCE(SUM(e.event_type='entry' AND v.counted=1),0) AS counted_entries_today, "
                "COALESCE(SUM(e.event_type='exit' AND v.counted=1),0) AS counted_exits_today, "
                "COALESCE(SUM(e.event_type='exit' AND v.status='returning'),0) AS returning_exits_today, "
                "COALESCE(SUM(e.event_type='exit' AND v.status='unverified'),0) AS unverified_exits_today, "
                "COALESCE(SUM(e.event_type='exit' AND v.status='pending'),0) AS pending_exits_today, "
                "COALESCE(SUM(e.event_type='exit' AND (v.status='disabled' OR v.status IS NULL)),0) "
                "AS unchecked_exits_today FROM events e LEFT JOIN visitor_events v ON e.id=v.event_id "
                "WHERE e.local_day=?",
                (local_day,),
            ).fetchone()
        balance = totals["entries"] - totals["exits"]
        return {
            "entries_today": day["entries"],
            "exits_today": day["exits"],
            "entries": totals["entries"],
            "exits": totals["exits"],
            "occupancy": max(0, balance),
            "inconsistent": balance < 0,
            "occupancy_uncertain": bool(totals["uncertain"]) or balance < 0,
            "occupancy_reason": totals["uncertainty_reason"],
            "date": local_day,
            "timezone": str(self.zone),
            "reset_at": totals["reset_at"],
            **dict(visitors),
            **dict(directions),
        }

    def reset_counters(self) -> None:
        with self.lock, self.connection:
            previous = self.connection.execute("SELECT * FROM counters WHERE singleton=1").fetchone()
            maximum = self.connection.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            # Después de retención, el marcador no puede retroceder.
            maximum = max(maximum, previous["reset_event_id"])
            now = utc_text(datetime.now(timezone.utc))
            self.connection.execute(
                "INSERT INTO resets(timestamp,previous_entries,previous_exits) VALUES(?,?,?)",
                (now, previous["entries"], previous["exits"]),
            )
            self.connection.execute(
                "UPDATE counters SET entries=0,exits=0,reset_event_id=?,reset_at=?,uncertain=0,uncertainty_reason='' WHERE singleton=1", (maximum, now)
            )

    def mark_occupancy_uncertain(self, reason):
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE counters SET uncertain=1,uncertainty_reason=? WHERE singleton=1 AND uncertain=0", (reason,)
            )

    def history(self, start: str, end: str, group: str = "hour") -> list[dict]:
        column = {"hour": "local_hour", "day": "local_day"}.get(group)
        if column is None:
            raise ValueError("Agrupación inválida.")
        with self.lock:
            rows = self.connection.execute(
                f"SELECT e.{column} AS period, SUM(e.event_type='entry') AS entries, "
                "SUM(e.event_type='exit') AS exits, "
                "COALESCE(SUM(e.event_type='entry' AND v.counted=1),0) AS counted_entries, "
                "COALESCE(SUM(e.event_type='exit' AND v.counted=1),0) AS counted_exits, "
                "COALESCE(SUM(e.event_type='entry' AND v.status='new'),0) AS unique_visitors, "
                "COALESCE(SUM(e.event_type='entry' AND v.status='returning'),0) AS returning_entries, "
                "COALESCE(SUM(e.event_type='exit' AND v.status='returning'),0) AS returning_exits, "
                "COALESCE(SUM(e.event_type='entry' AND v.status='unverified'),0) AS unverified_entries, "
                "COALESCE(SUM(e.event_type='exit' AND v.status='unverified'),0) AS unverified_exits, "
                "COALESCE(SUM(e.event_type='entry' AND v.status='pending'),0) AS pending_entries, "
                "COALESCE(SUM(e.event_type='exit' AND v.status='pending'),0) AS pending_exits, "
                "SUM(e.event_type='entry' AND (v.status='disabled' OR v.status IS NULL)) AS unchecked_entries, "
                "SUM(e.event_type='exit' AND (v.status='disabled' OR v.status IS NULL)) AS unchecked_exits "
                "FROM events e LEFT JOIN visitor_events v ON e.id=v.event_id "
                "WHERE e.local_day BETWEEN ? AND ? "
                f"GROUP BY e.{column} ORDER BY e.{column}",
                (start, end),
            ).fetchall()
        return [dict(row) for row in rows]

    def iter_events(self, start: str, end: str):
        """Paginación estable y memoria limitada durante la descarga CSV."""
        after = 0
        with self.lock:
            maximum = self.connection.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        while True:
            with self.lock:
                rows = self.connection.execute(
                    "SELECT e.*, v.status AS visitor_status, v.reason AS visitor_reason, "
                    "COALESCE(v.counted,0) AS counted, v.evidence AS evidence "
                    "FROM events e LEFT JOIN visitor_events v ON e.id=v.event_id "
                    "WHERE e.local_day BETWEEN ? AND ? AND e.id>? AND e.id<=? ORDER BY e.id LIMIT 500",
                    (start, end, after, maximum),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield dict(row)
            after = rows[-1]["id"]

    def prune(self, retention_days: int, now: datetime | None = None) -> None:
        local = (now or datetime.now(timezone.utc)).astimezone(self.zone)
        cutoff = (local.date() - timedelta(days=retention_days)).isoformat()
        with self.lock, self.connection:
            # Los IDs del tracker nunca se reutilizan en una sesión. Los flags de tracks
            # visibles mantienen la deduplicación aunque expire el historial en disco.
            self.connection.execute("DELETE FROM events WHERE local_day<?", (cutoff,))
            unused = self.connection.execute(
                "SELECT id FROM sessions WHERE substr(started_at,1,10)<? AND "
                "NOT EXISTS(SELECT 1 FROM events WHERE events.session_id=sessions.id)",
                (cutoff,),
            ).fetchall()
            self.connection.executemany(
                "DELETE FROM sessions WHERE id=?",
                [(row["id"],) for row in unused if row["id"] not in self.active_sessions],
            )
            self.connection.execute("DELETE FROM resets WHERE substr(timestamp,1,10)<?", (cutoff,))
        # SQLite reutiliza las páginas libres sin VACUUM que bloquee el conteo.

    def purge_visitors(self, now: datetime | None = None) -> int:
        with self.lock, self.connection:
            count = self.connection.execute(
                "DELETE FROM visitors WHERE expires_at<=?", (utc_text(now or datetime.now(timezone.utc)),)
            ).rowcount
        if count:
            self.checkpoint()
        return count

    def checkpoint(self) -> None:
        with self.lock:
            try:
                self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError:
                log.debug("Checkpoint aplazado por una transacción activa.")

    def close(self) -> None:
        with self.lock:
            if not self.closed:
                self.checkpoint()
                self.connection.close()
                self.closed = True


def validate_range(start: str, end: str) -> tuple[str, str]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Usa fechas YYYY-MM-DD.") from exc
    if first > last or (last - first).days > 366:
        raise ValueError("Selecciona un rango ordenado de hasta 367 días.")
    return first.isoformat(), last.isoformat()
