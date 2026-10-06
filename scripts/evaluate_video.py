"""Regresión de un video completo, con modelos reales y datos temporales aislados.

No entrena pesos ni escribe en data/ de la instalación. El informe no contiene
vectores ni identificadores de la galería. --render genera video MP4 sin audio.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera_counter.config import Config, LineConfig  # noqa: E402
from camera_counter.counting.line_counter import LineCounter  # noqa: E402
from camera_counter.database.repository import Repository  # noqa: E402
from camera_counter.detection.detector import YOLODetector  # noqa: E402
from camera_counter.detection.tracker import PersonTracker  # noqa: E402
from camera_counter.utils.video import annotate  # noqa: E402
from camera_counter.visitors.body import BodyRecognizer  # noqa: E402
from camera_counter.visitors.recognizer import FaceRecognizer  # noqa: E402
from camera_counter.visitors.service_hybrid import HybridVisitorService  # noqa: E402


class MeasuredBackend:
    def __init__(self, backend, visible_until=float("inf")):
        self.backend = backend
        self.model_id = backend.model_id
        self.visible_until = visible_until
        self.timeline = 0.0
        self.calls = self.samples = 0

    def extract(self, frame, people, eligible):
        if self.timeline > self.visible_until:
            return {}
        self.calls += 1
        result = self.backend.extract(frame, people, eligible)
        self.samples += len(result)
        return result


def check_continuity(service, counter, repository):
    uncertain = counter.invalidate(service.take_invalidated_tracks())
    if uncertain or counter.lost_inside:
        repository.mark_occupancy_uncertain("tracking_interrupted_inside")
    counter.lost_inside.clear()


def evaluate(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else {}
    with args.video.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if manifest.get("sha256", digest) != digest:
        raise ValueError("El video no corresponde al SHA-256 del manifiesto. Usa su manifiesto correcto.")
    if args.no_face and args.mode == "face":
        raise ValueError("--no-face requiere --mode hybrid.")
    args.output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError("No se pudo abrir el video.")
    fps = cap.get(cv2.CAP_PROP_FPS)
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not (0 < fps <= 240 and width > 0 and height > 0):
        cap.release()
        raise ValueError("Dimensiones/FPS del video inválidos.")
    start_time = datetime.fromisoformat(manifest.get("start_time_utc", datetime.now(timezone.utc).isoformat()))
    if start_time.tzinfo is None:
        cap.release()
        raise ValueError("El tiempo inicial necesita zona horaria.")
    writer = None
    try:
        with TemporaryDirectory(prefix="camera_counter_evaluation_") as temporary:
            cfg = Config(base_dir=Path(temporary))
            cfg.camera.type, cfg.camera.width, cfg.camera.height, cfg.camera.fps = "video", width, height, fps
            cfg.detection.model = str(ROOT / "models/yolo11n.pt")
            cfg.detection.image_size = manifest.get("image_size", 640)
            cfg.visitors.mode = args.mode
            for name in ("detector_model", "recognizer_model", "body_model"):
                setattr(cfg.visitors, name, str(ROOT / getattr(cfg.visitors, name)))
            if "line" in manifest:
                cfg.line = LineConfig(**manifest["line"])
            cfg.validate()
            cv2.setNumThreads(cfg.detection.cpu_threads)
            repo = Repository(Path(temporary) / "counter.sqlite3", cfg.storage.timezone)
            until = -1 if args.no_face else args.face_until
            face = MeasuredBackend(FaceRecognizer(cfg), until)
            body = MeasuredBackend(BodyRecognizer(cfg)) if args.mode == "hybrid" else None
            service = HybridVisitorService(cfg, repo, backend=face, body_backend=body)
            service.start(start_time)
            session = repo.start_session("video_regression", start_time)
            detector, tracker = YOLODetector(cfg), PersonTracker(cfg)
            counter = LineCounter(cfg.line, width, height)
            if args.render:
                writer = cv2.VideoWriter(str(args.output / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                if not writer.isOpened():
                    raise RuntimeError("No se pudo crear el MP4 de prueba.")
            frame_number, seen_ids, errors = 0, set(), set()
            started = time.monotonic()
            scene_counts = [0] * len(manifest.get("scenes", []))
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                timeline = frame_number / fps
                timestamp = start_time + timedelta(seconds=timeline)
                face.timeline = timeline
                people = tracker.update(detector.detect(frame), frame, timeline)
                seen_ids.update(p.track_id for p in people)
                service.observe(frame, people, timeline, timestamp)
                check_continuity(service, counter, repo)
                for event in counter.update(people, timeline, timestamp):
                    service.record(event, session, timeline)
                service.flush(timeline, timestamp)
                check_continuity(service, counter, repo)
                error = service.status(timestamp)["error"]
                if error:
                    errors.add(error)
                for i, scene in enumerate(manifest.get("scenes", [])):
                    if scene["start"] <= timeline < scene["end"]:
                        scene_counts[i] += 1
                if writer is not None:
                    stats = repo.stats(timestamp)
                    label = "PRUEBA SIN RECONOCIMIENTO FACIAL" if args.no_face else "Prueba de identidad hibrida"
                    rendered = annotate(frame, people, counter, stats, (frame_number + 1) / max(.01, time.monotonic() - started), label, service.track_labels())
                    cv2.rectangle(rendered, (0, height - 52), (width, height), (29, 31, 30), -1)
                    cv2.putText(rendered, f"t={timeline:.2f}s | Cruces fisicos: {stats['entries_today']} entrada / {stats['exits_today']} salida", (12, height - 31), cv2.FONT_HERSHEY_SIMPLEX, .48, (220, 230, 220), 1, cv2.LINE_AA)
                    cv2.putText(rendered, "Linea virtual de prueba | Repeticiones no suman a Entradas/Salidas/Unicos", (12, height - 10), cv2.FONT_HERSHEY_SIMPLEX, .43, (164, 180, 172), 1, cv2.LINE_AA)
                    writer.write(rendered)
                frame_number += 1
                if frame_number % 240 == 0:
                    print(f"{frame_number} fotogramas, {time.monotonic() - started:.1f} s de proceso", flush=True)
            if frame_number == 0:
                raise RuntimeError("El video no contiene fotogramas decodificables.")
            ended = start_time + timedelta(seconds=(frame_number - 1) / fps)
            labels_at_end = service.track_labels()
            service.finish("video_complete", ended)
            stats = repo.stats(ended)
            begin_day = start_time.astimezone(repo.zone).date().isoformat()
            events = list(repo.iter_events(begin_day, stats["date"]))
            crossings = [{"seconds": round((datetime.fromisoformat(e["timestamp"]) - start_time).total_seconds(), 3), "direction": e["event_type"], "status": e["visitor_status"], "reason": e["visitor_reason"], "evidence": e["evidence"], "counted": e["counted"]} for e in events]
            mismatches = {key: {"expected": value, "actual": stats.get(key)} for key, value in manifest.get("expected", {}).items() if stats.get(key) != value}
            for key, value in (("frames", frame_number), ("width", width), ("height", height)):
                if key in manifest and manifest[key] != value:
                    mismatches[key] = {"expected": manifest[key], "actual": value}
            report = {
                "video_sha256": digest, "frames": frame_number, "fps": fps, "width": width, "height": height,
                "mode": args.mode, "face_disabled": args.no_face, "face_until": None if args.face_until == float("inf") else args.face_until,
                "models": {"face": face.model_id, "body": body.model_id if body else None},
                "samples": {"face": face.samples, "body": body.samples if body else 0},
                "inference_calls": {"face": face.calls, "body": body.calls if body else 0},
                "processed_seconds": round(time.monotonic() - started, 3),
                "tracker_ids_seen": len(seen_ids), "stats": stats, "crossings": crossings,
                "decisions": dict(Counter(f"{e['visitor_status']}:{e['evidence']}" for e in events)),
                "scenes": [{**s, "frames_processed": n, "crossings": [e for e in crossings if s["start"] <= e["seconds"] < s["end"]]} for s, n in zip(manifest.get("scenes", []), scene_counts)],
                "labels_at_end": list(labels_at_end.values()), "errors": sorted(errors),
                "expected_mismatches": mismatches, "passed": not mismatches and not errors,
                "fine_tuned_on_video": False, "evaluation": "full_video_actual_models",
                "limitations": manifest.get("limitations", ["No hay conteo esperado independiente para este video."]),
                "versions": {name: importlib.metadata.version(name) for name in ("ultralytics", "torch", "numpy", "opencv-python", "cryptography")},
            }
            repo.end_session(session)
            repo.close()
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"passed": report["passed"], "frames": frame_number, "stats": stats, "samples": report["samples"], "errors": report["errors"], "mismatches": mismatches}, ensure_ascii=False), flush=True)
            return 0 if report["passed"] else 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, help="Línea, tomas y expectativas; verifica el SHA-256 del video.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("hybrid", "face"), default="hybrid")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--no-face", action="store_true")
    group.add_argument("--face-until", type=float, default=float("inf"), help="Segundos hasta desactivar la extracción facial.")
    parser.add_argument("--render", action="store_true")
    return evaluate(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
