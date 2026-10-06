"""Descarga explícita de modelos oficiales de OpenCV Zoo, verificados con SHA-256."""

import argparse
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "face_detection_yunet",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        232589,
    ),
    "face_recognition_sface_2021dec.onnx": (
        "face_recognition_sface",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        38696353,
    ),
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(directory, check=False):
    directory.mkdir(parents=True, exist_ok=True)
    for name, (folder, expected, size) in MODELS.items():
        target = directory / name
        if target.is_file() and target.stat().st_size == size and digest(target) == expected:
            print(name + ": verificado")
            continue
        if check:
            raise RuntimeError(name + ": falta el modelo o su contenido no coincide con el oficial.")
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{name}"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False, suffix=".download") as output:
                temporary = Path(output.name)
                request = urllib.request.Request(url, headers={"User-Agent": "CameraCounter/2"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > size:
                            raise RuntimeError("Tamaño inesperado: " + name)
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if total != size or digest(temporary) != expected:
                raise RuntimeError("Falló la verificación SHA-256: " + name)
            temporary.replace(target)
            print(name + ": descargado y verificado")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "models")
    parser.add_argument("--check", action="store_true", help="Verificar archivos sin acceder a internet")
    args = parser.parse_args()
    try:
        download(args.directory, args.check)
    except (OSError, RuntimeError) as exc:
        parser.exit(1, str(exc) + "\n")
