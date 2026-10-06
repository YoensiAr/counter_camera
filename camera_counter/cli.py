import argparse
import json
import logging
import signal

from camera_counter.config import load_config
from camera_counter.utils.logging import setup_logging
from camera_counter.utils.platform import platform_details


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Contador local de entradas y salidas con YOLO y tracking.")
    parser.add_argument("--config", help="Archivo YAML")
    parser.add_argument(
        "--camera", choices=["auto", "usb", "opencv", "csi", "picamera2", "imx500", "rtsp", "video", "mock", "browser"]
    )
    parser.add_argument("--source", help="Índice de cámara, archivo o URL; también CAMERA_COUNTER_SOURCE")
    parser.add_argument("--video", help="Procesar un archivo de video")
    parser.add_argument("--simulate", action="store_true", help="Cámara sintética con ByteTrack real, sin pesos YOLO")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--headless", action="store_true", help="Sin ventana OpenCV; el panel puede seguir activo")
    display.add_argument("--gui", action="store_true", help="Mostrar ventana de escritorio")
    web = parser.add_mutually_exclusive_group()
    web.add_argument("--web", action="store_true", help="Activar el panel web")
    web.add_argument("--no-web", action="store_true", help="Desactivar el panel web")
    parser.add_argument("--host", help="127.0.0.1 para este equipo, 0.0.0.0 para la red local")
    parser.add_argument("--port", type=int, help="Puerto del panel")
    parser.add_argument("--diagnose", action="store_true", help="Diagnóstico sin modificar contadores ni grabar")
    parser.add_argument("--max-frames", type=int, help="Detenerse tras N fotogramas procesados")
    parser.add_argument("--fast", action="store_true", help="Archivos/simulación sin espera de reproducción")
    args = parser.parse_args(argv)
    runtime = None
    previous_handlers = {}
    try:
        cfg = load_config(args.config)
        if args.camera:
            cfg.camera.type = args.camera
        if args.source is not None:
            cfg.camera.source = int(args.source) if args.source.isdecimal() else args.source
        if args.video:
            from pathlib import Path

            cfg.camera.type, cfg.camera.source = "video", str(Path(args.video).resolve())
        if args.simulate:
            cfg.camera.type = "mock"
        if args.headless:
            cfg.gui = False
        if args.gui:
            cfg.gui = True
        if args.no_web:
            cfg.web.enabled = False
        if args.web:
            cfg.web.enabled = True
        if args.host:
            cfg.web.host = args.host
        if args.port is not None:
            cfg.web.port = args.port
        if args.fast:
            cfg.camera.realtime = False
        if args.max_frames is not None and args.max_frames < 1:
            raise ValueError("max-frames debe ser mayor que cero.")
        if args.diagnose:
            cfg.web.enabled = cfg.gui = cfg.recording.enabled = False
        cfg.validate()
        setup_logging(cfg.path(cfg.storage.log_directory))
        from camera_counter.app import CounterApplication
        from camera_counter.database.repository import Repository

        diagnostic_db = Repository(":memory:", cfg.storage.timezone) if args.diagnose else None
        runtime = CounterApplication(cfg, repository=diagnostic_db)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_: runtime.stop_event.set())
        result = runtime.run(
            max_frames=args.max_frames or (60 if args.diagnose else None),
            deadline_seconds=45 if args.diagnose else None,
        )
        if args.diagnose or args.max_frames:
            result["platform"] = platform_details()
            result["running"] = False
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        logging.getLogger(__name__).error("%s", exc or "Interrumpido por el usuario.")
        return 1
    finally:
        if runtime is not None:
            runtime.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
