"""Descarga explícita del modelo nano oficial; el servicio nunca lo descarga solo."""

import argparse
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Descargar YOLO11n oficial para uso local.")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "models/yolo11n.pt")
    args = parser.parse_args()
    if args.output.exists():
        print(f"El modelo ya existe: {args.output}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".part")
    url = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 50 * 1024 * 1024:
                    raise RuntimeError("La descarga excede el tamaño esperado para un modelo nano.")
                output.write(chunk)
        temporary.replace(args.output)
        print(f"Modelo guardado: {args.output}")
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
