"""API local con validación, CSRF y autenticación opcional por entorno."""

import csv
import io
import os
import secrets
import threading
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

from camera_counter.database.repository import validate_range


def create_app(runtime) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024
    csrf = secrets.token_urlsafe(32)
    app.config["CSRF_TOKEN"] = csrf
    password = os.environ.get("CAMERA_COUNTER_WEB_TOKEN", "")
    streams = threading.BoundedSemaphore(runtime.config.web.max_stream_clients)

    @app.before_request
    def guard():
        if password:
            auth = request.authorization
            if (
                not auth
                or auth.username != "admin"
                or not secrets.compare_digest((auth.password or "").encode("utf-8"), password.encode("utf-8"))
            ):
                return Response(
                    "Se requiere acceso al panel.",
                    401,
                    {"WWW-Authenticate": 'Basic realm="Camera Counter", charset="UTF-8"'},
                )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not secrets.compare_digest(request.headers.get("X-CSRF-Token", "").encode("utf-8"), csrf.encode()):
                return jsonify(error="Solicitud inválida. Recarga el panel."), 403
            if request.path == "/api/camera/frame":
                if request.mimetype not in {"image/jpeg", "image/jpg"}:
                    return jsonify(error="El fotograma debe enviarse como image/jpeg."), 415
            elif not request.is_json:
                return jsonify(error="Se requiere contenido JSON."), 415

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.errorhandler(ValueError)
    def validation_error(exc):
        return jsonify(error=str(exc)), 400

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Se requiere un objeto JSON.")
        return data

    def dates():
        today = datetime.now(runtime.repository.zone).date()
        return validate_range(
            request.args.get("start", (today - timedelta(days=6)).isoformat()),
            request.args.get("end", today.isoformat()),
        )

    @app.get("/")
    def dashboard():
        return render_template("index.html", csrf=csrf)

    @app.get("/api/status")
    def status():
        return jsonify(runtime.snapshot())

    @app.post("/api/camera/frame")
    def browser_frame():
        if runtime.config.camera.type != "browser":
            return jsonify(error="Este servidor no usa la cámara del navegador."), 409
        data = request.get_data(cache=False)
        if not data:
            raise ValueError("Se recibió un fotograma vacío.")
        runtime.submit_browser_frame(data)
        return jsonify(ok=True), 202

    @app.get("/healthz")
    def health():
        snapshot = runtime.snapshot()
        visitors = snapshot["visitors"]
        face_ok = visitors["mode"] not in {"face", "hybrid"} or (visitors["active"] and not visitors["error"])
        ok = snapshot["running"] and not snapshot["error"] and not snapshot["camera_error"] and face_ok
        return jsonify(ok=ok, camera=snapshot["camera"], frames=snapshot["processed_frames"]), 200 if ok else 503

    @app.get("/video_feed")
    def video():
        if not streams.acquire(blocking=False):
            return jsonify(error="Se alcanzó el límite de espectadores de video."), 429
        response = Response(runtime.stream(), mimetype="multipart/x-mixed-replace; boundary=frame")
        response.call_on_close(streams.release)
        return response

    @app.get("/api/history")
    def history():
        start, end = dates()
        return jsonify(runtime.repository.history(start, end, request.args.get("group", "hour")))

    @app.post("/api/line")
    def line():
        try:
            return jsonify(line=runtime.change_line(payload()))
        except OSError:
            return jsonify(error="No se pudo guardar config.yaml. Revisa los permisos del archivo."), 500

    @app.post("/api/reset")
    def reset():
        if payload().get("confirm") is not True:
            raise ValueError("Debes confirmar el reinicio de contadores.")
        runtime.reset_counters()
        return jsonify(ok=True)

    @app.post("/api/recording")
    def recording():
        data = payload()
        if not isinstance(data.get("enabled"), bool):
            raise ValueError("enabled debe ser true o false.")
        runtime.set_recording(data["enabled"])
        return jsonify(enabled=data["enabled"])

    @app.post("/api/visitors")
    def visitors_settings():
        try:
            return jsonify(visitors=runtime.change_visitors(payload()))
        except OSError:
            return jsonify(error="No se pudo guardar la configuración. Revisa los permisos."), 500
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409

    @app.post("/api/visitors/forget")
    def visitors_forget():
        if payload().get("confirm") is not True:
            raise ValueError("Debes confirmar el borrado de las referencias faciales.")
        runtime.forget_visitors()
        return jsonify(ok=True)

    @app.get("/reports/events.csv")
    def report():
        start, end = dates()

        def safe(value):
            value = str(value)
            return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value

        def generate():
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            yield "\ufeff"
            writer.writerow(
                [
                    "fecha_utc",
                    "dia_local",
                    "tipo",
                    "track_id_temporal",
                    "camara",
                    "confianza_promedio",
                    "direccion",
                    "sesion",
                    "cruce_del_track",
                    "clasificacion_visita",
                    "motivo_verificacion",
                    "suma_al_contador",
                    "evidencia",
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            for event in runtime.repository.iter_events(start, end):
                writer.writerow(
                    [
                        safe(event["timestamp"]),
                        event["local_day"],
                        "entrada" if event["event_type"] == "entry" else "salida",
                        event["track_id"],
                        safe(event["source"]),
                        round(event["confidence"], 4),
                        safe(event["direction"]),
                        event["session_id"],
                        event["crossing_index"],
                        event["visitor_status"] or ("legacy" if event["event_type"] == "entry" else ""),
                        event["visitor_reason"] or "",
                        event["counted"],
                        event["evidence"] or "",
                    ]
                )
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

        return Response(
            generate(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="conteos_{start}_{end}.csv"'},
        )

    @app.get("/reports/summary.csv")
    def summary_report():
        start, end = dates()
        rows = runtime.repository.history(start, end, request.args.get("group", "hour"))
        output = io.StringIO(newline="")
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow(["periodo", "visitantes_unicos", "reingresos", "sin_verificar", "entradas", "salidas"])
        for row in rows:
            unverified = sum(
                row[key]
                for key in (
                    "unverified_entries", "unverified_exits", "pending_entries", "pending_exits",
                    "unchecked_entries", "unchecked_exits",
                )
            )
            writer.writerow([
                row["period"], row["unique_visitors"], row["returning_entries"], unverified,
                row["counted_entries"], row["counted_exits"],
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="totales_{start}_{end}.csv"'},
        )

    return app
