"""Identidad temporal multimodal y conteo atómico; los casos ambiguos esperan evidencia."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import uuid

import numpy as np
from cryptography.fernet import InvalidToken

from camera_counter.database.repository import utc_text
from camera_counter.visitors.body import body_vector
from camera_counter.visitors.store import VisitorStore, expires_at, normalize


@dataclass(frozen=True)
class Match:
    kind: str  # match, new, wait, conflict
    visitor_id: str | None = None
    evidence: str = ""
    reason: str = ""
    similarity: float | None = None


class HybridStore(VisitorStore):
    def __init__(self, repository, config, key_path, face_model_id, body_model_id):
        super().__init__(repository, config, key_path, face_model_id)
        self.body_model_id = body_model_id
        self._cache = OrderedDict()
        with repository.lock:
            incompatible = repository.connection.execute(
                "SELECT COUNT(*) FROM visitor_bodies WHERE model_id!=?", (body_model_id,)
            ).fetchone()[0]
        if incompatible:
            raise RuntimeError("Las referencias corporales pertenecen a otro modelo. Restaura el OSNet original o espera su caducidad.")

    def clear_cache(self):
        self._cache.clear()

    def _gallery(self, now):
        rows = self.repository.connection.execute(
            "SELECT v.id,v.template,v.face_ready,v.expires_at,b.template AS body_template "
            "FROM visitors v LEFT JOIN visitor_bodies b ON b.visitor_id=v.id WHERE v.expires_at>?",
            (utc_text(now),),
        ).fetchall()
        result = {}
        live = {r["id"] for r in rows}
        for key in list(self._cache):
            if key not in live:
                del self._cache[key]
        for row in rows:
            key = row["id"]
            signature = (row["template"], row["body_template"], row["face_ready"])
            cached = self._cache.get(key)
            if cached and cached[0] == signature:
                face, bodies = cached[1:]
                self._cache.move_to_end(key)
            else:
                try:
                    face = normalize(np.frombuffer(self.cipher.decrypt(row["template"]), dtype="<f4")) if row["face_ready"] else None
                    raw = self.cipher.decrypt(row["body_template"]) if row["body_template"] else b""
                    if len(raw) % (512 * 4) or len(raw) > 12 * 512 * 4:
                        raise ValueError("Tamaño de plantilla corporal inválido.")
                    bodies = np.array([body_vector(v) for v in np.frombuffer(raw, dtype="<f4").reshape(-1, 512)])
                except (ValueError, InvalidToken) as exc:
                    raise RuntimeError("Una referencia no se puede descifrar o está dañada. Revisa la base y su clave.") from exc
                self._cache[key] = (signature, face, bodies)
                while len(self._cache) > 1024:
                    self._cache.popitem(last=False)
            result[key] = (face, bodies)
        return result

    def _features(self, face_samples, body_samples):
        face, bodies = None, None
        if len(face_samples) >= self.config.min_samples:
            vectors = np.array([normalize(v) for v in face_samples])
            if float((vectors @ vectors.T).min()) < self.config.match_threshold:
                return None, None, "inconsistent_face_samples"
            face = normalize(vectors.mean(axis=0))
        if len(body_samples) >= self.config.body_min_samples:
            vectors = np.array([body_vector(v) for v in body_samples])
            if float((vectors @ vectors.T).min()) >= self.config.body_consistency_threshold:
                bodies = vectors
            elif face is None:
                return None, None, "inconsistent_body_samples"
        return face, bodies, ""

    def _select(self, gallery, face, bodies, hint, excluded):
        cfg = self.config
        # Una cara fiable que contradice la identidad anterior invalida la continuidad.
        if hint in gallery and face is not None:
            saved = gallery[hint][0]
            if saved is not None and float(face @ saved) <= cfg.new_threshold:
                return Match("conflict", reason="face_identity_conflict")

        face_rank = sorted(
            ((float(face @ saved), key) for key, (saved, _) in gallery.items() if saved is not None), reverse=True
        ) if face is not None else []
        body_rank = sorted(
            ((float(np.min(np.max(bodies @ views.T, axis=1))), key)
             for key, (_, views) in gallery.items() if len(views)), reverse=True
        ) if bodies is not None else []
        if face_rank and face_rank[0][0] >= cfg.match_threshold:
            score, key = face_rank[0]
            second = face_rank[1][0] if len(face_rank) > 1 else -1.0
            if score - second < cfg.ambiguity_margin:
                return Match("wait", reason="ambiguous_face", similarity=score)
            if key in excluded:
                return Match("wait", reason="identity_visible_elsewhere", similarity=score)
            return Match("match", key, "face", similarity=score)

        if hint in gallery:
            if hint in excluded:
                return Match("wait", reason="identity_visible_elsewhere")
            # La pista solo procede de un track observado, próximo y sin oclusión.
            return Match("match", hint, "continuity")

        face_uncertain = bool(face_rank and face_rank[0][0] > cfg.new_threshold)
        if face_uncertain:
            return Match("wait", reason="uncertain_face", similarity=face_rank[0][0])
        if body_rank and body_rank[0][0] >= cfg.body_match_threshold:
            score, key = body_rank[0]
            second = body_rank[1][0] if len(body_rank) > 1 else -1.0
            saved_face = gallery[key][0]
            if face is not None and saved_face is not None and float(face @ saved_face) <= cfg.new_threshold:
                # Personas de ropa similar, con caras claramente distintas, no se fusionan.
                return Match("new", evidence="face", reason="different_face")
            if score - second < cfg.body_ambiguity_margin:
                return Match("wait", reason="ambiguous_body", similarity=score)
            if key in excluded:
                return Match("wait", reason="identity_visible_elsewhere", similarity=score)
            return Match("match", key, "body", similarity=score)
        if body_rank and body_rank[0][0] > cfg.body_new_threshold:
            # Una cara nueva inequívoca permite distinguir a dos personas vestidas parecido.
            if face is not None and all(saved is not None for saved, _ in gallery.values()):
                return Match("new", evidence="face", reason="different_face")
            return Match("wait", reason="uncertain_body", similarity=body_rank[0][0])
        if face is None and bodies is None:
            return Match("wait", reason="insufficient_evidence")
        if face is None and any(not len(views) for _, views in gallery.values()):
            return Match("wait", reason="reference_without_body")
        if bodies is None and any(saved is None for saved, _ in gallery.values()):
            return Match("wait", reason="reference_without_face")
        return Match("new", evidence="face" if face is not None else "body", reason="distinct_reference")

    def match(self, face_samples, body_samples, now, *, hint=None, excluded=()):
        face, bodies, error = self._features(face_samples, body_samples)
        if error:
            return Match("wait", reason=error)
        with self.repository.lock:
            return self._select(self._gallery(now), face, bodies, hint, set(excluded))

    def classify(self, event_id, samples, now, *, body_samples=(), hint=None, excluded=(), allow_new=True):
        face, bodies, error = self._features(samples, body_samples)
        repo = self.repository
        with repo.lock, repo.connection:
            repo.connection.execute("BEGIN IMMEDIATE")
            event = repo.connection.execute(
                "SELECT e.timestamp,e.event_type,v.status FROM events e JOIN visitor_events v ON e.id=v.event_id WHERE e.id=?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise ValueError("El cruce no existe.")
            if event["status"] != "pending":
                return event["status"]
            created = datetime.fromisoformat(event["timestamp"])
            expiry = expires_at(created, self.config, repo.zone)
            if now >= expiry:
                return self._resolve(event_id, "unverified", "window_expired", now)
            gallery = self._gallery(now)
            decision = Match("wait", reason=error) if error else self._select(gallery, face, bodies, hint, set(excluded))
            if decision.kind == "new" and not allow_new and face is None:
                decision = Match("wait", reason="lost_identity_needs_confirmation")
            if decision.kind in {"wait", "conflict"}:
                repo.connection.execute(
                    "UPDATE visitor_events SET reason=?,similarity=? WHERE event_id=? AND status='pending'",
                    (decision.reason, decision.similarity, event_id),
                )
                return "pending"
            key = decision.visitor_id
            if decision.kind == "new":
                if len(gallery) >= self.config.max_identities:
                    return self._resolve(event_id, "unverified", "capacity", now)
                key = uuid.uuid4().hex
                repo.connection.execute(
                    "INSERT INTO visitors(id,model_id,template,created_at,expires_at,face_ready) VALUES(?,?,?,?,?,?)",
                    (key, self.model_id, self.cipher.encrypt(face.astype("<f4").tobytes() if face is not None else b""),
                     utc_text(created), utc_text(expiry), int(face is not None)),
                )
                if bodies is not None:
                    self._save_views(key, bodies, now)
            elif face is not None and gallery[key][0] is None:
                # Solo una vinculación corporal/continua ya aceptada puede añadir la cara ausente.
                repo.connection.execute(
                    "UPDATE visitors SET template=?,face_ready=1,model_id=? WHERE id=?",
                    (self.cipher.encrypt(face.astype("<f4").tobytes()), self.model_id, key),
                )
            result = self._count_direction(event_id, event["event_type"], key, now, decision.similarity, evidence=decision.evidence)
        return result

    def event_identity(self, event_id):
        with self.repository.lock:
            row = self.repository.connection.execute(
                "SELECT visitor_id,evidence FROM visitor_events WHERE event_id=? AND status IN ('new','returning')", (event_id,)
            ).fetchone()
        return (row[0], row[1]) if row else (None, "")

    def _save_views(self, key, views, now):
        # Conserva la primera vista como ancla; las otras cubren orientaciones distintas.
        selected = []
        for raw in views:
            vector = body_vector(raw)
            if selected and max(float(vector @ old) for old in selected) >= .97:
                continue
            selected.append(vector)
            if len(selected) > self.config.body_max_views:
                matrix = np.array(selected) @ np.array(selected).T
                np.fill_diagonal(matrix, -1)
                redundancy = matrix.max(axis=1)
                # La vista nueva solo entra si amplía la diversidad de las ya guardadas.
                remove = 1 + int(np.argmax(redundancy[1:]))
                selected.pop(remove)
        if not selected:
            return
        raw = np.asarray(selected, dtype="<f4").tobytes()
        self.repository.connection.execute(
            "INSERT INTO visitor_bodies(visitor_id,model_id,template,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(visitor_id) DO UPDATE SET template=excluded.template,updated_at=excluded.updated_at",
            (key, self.body_model_id, self.cipher.encrypt(raw), utc_text(now)),
        )
        self._cache.pop(key, None)

    def remember(self, key, faces, bodies, now, *, learn_body=False):
        """Aprende vistas solo en continuidad comprobada; nunca amplía la caducidad."""
        face, current, error = self._features(faces, bodies)
        if error:
            return False
        repo = self.repository
        with repo.lock, repo.connection:
            repo.connection.execute("BEGIN IMMEDIATE")
            gallery = self._gallery(now)
            if key not in gallery:
                return False
            saved_face, views = gallery[key]
            if face is not None and saved_face is not None and float(face @ saved_face) < self.config.match_threshold:
                return False
            if face is not None and saved_face is None:
                repo.connection.execute(
                    "UPDATE visitors SET template=?,face_ready=1,model_id=? WHERE id=?",
                    (self.cipher.encrypt(face.astype("<f4").tobytes()), self.model_id, key),
                )
            if current is not None and (learn_body or face is not None):
                additions = [v for v in current if not len(views) or float(np.max(views @ v)) < .97]
                if additions:
                    self._save_views(key, list(views) + additions, now)
        return True

    def set_window(self, config, now):
        super().set_window(config, now)
        self.clear_cache()
