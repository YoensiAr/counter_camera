"""Comprueba el OSNet incluido, sin descargas ni escritura de datos de visitantes."""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera_counter.config import Config  # noqa: E402
from camera_counter.visitors.body import BodyRecognizer  # noqa: E402


def main():
    manifest = json.loads((ROOT / "models/osnet_manifest.json").read_text(encoding="utf-8"))
    path = ROOT / "models" / manifest["model"]
    if not path.is_file():
        raise SystemExit("Falta OSNet. Copia models/osnet_x0_25_msmt17.onnx del ZIP de la versión 3.")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if path.stat().st_size != manifest["bytes"] or digest != manifest["sha256"]:
        raise SystemExit("OSNet no coincide con el manifiesto. Restaura el archivo del ZIP.")
    backend = BodyRecognizer(Config(base_dir=ROOT))
    print(f"OSNet correcto: {path.stat().st_size} bytes, salida de 512 valores, OpenCV CPU.")
    print(backend.model_id)


if __name__ == "__main__":
    main()
