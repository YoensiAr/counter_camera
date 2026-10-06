"""Enumerar USB o ejecutar el diagnóstico completo sin tocar los contadores."""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Probar la cámara.")
    parser.add_argument("--scan-usb", action="store_true")
    args, extra = parser.parse_known_args()
    if args.scan_usb:
        import cv2

        found = []
        for index in range(6):
            camera = cv2.VideoCapture(index, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
            try:
                if camera.isOpened():
                    found.append(index)
            finally:
                camera.release()
        print("Cámaras USB disponibles:", found)
        return 0 if found else 1
    entry = Path(__file__).resolve().parents[1] / "main.py"
    return subprocess.call([sys.executable, str(entry), "--diagnose", *extra])


if __name__ == "__main__":
    raise SystemExit(main())
