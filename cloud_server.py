"""WSGI entrypoint para AWS/Render/Railway/VPS con cámara capturada en el navegador."""

from __future__ import annotations

import atexit
import logging
import os
import threading

from camera_counter.app import CounterApplication
from camera_counter.config import load_config
from camera_counter.utils.logging import setup_logging
from camera_counter.web.routes import create_app

CONFIG_PATH = os.environ.get("CAMERA_COUNTER_CONFIG", "config.cloud.yaml")
config = load_config(CONFIG_PATH)
config.camera.type = "browser"
config.gui = False
config.web.enabled = False  # El WSGI externo sirve Flask; evita levantar otro Waitress interno.
config.validate()
setup_logging(config.path(config.storage.log_directory))

runtime = CounterApplication(config)
_runtime_thread = threading.Thread(target=runtime.run, name="counter-runtime", daemon=True)
_runtime_thread.start()
app = create_app(runtime)
application = app


def _shutdown() -> None:
    try:
        runtime.close()
    except Exception:
        logging.getLogger(__name__).exception("No se pudo cerrar Camera Counter correctamente.")


atexit.register(_shutdown)

if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), threads=8)
