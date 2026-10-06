#!/usr/bin/env bash
set -euo pipefail
counter_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$counter_root"
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo 'Este instalador necesita Raspberry Pi OS de 64 bits (aarch64).' >&2
  exit 1
fi
sudo apt update
sudo apt install -y python3-venv python3-pip python3-picamera2 python3-opencv python3-numpy rpicam-apps imx500-all
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
# Mantener la ABI de NumPy usada por Picamera2 y los paquetes binarios de apt.
python3 - <<'PY'
from pathlib import Path
import numpy
Path("numpy-system-constraints.txt").write_text(f"numpy=={numpy.__version__}\n",encoding="utf-8")
PY
.venv/bin/python -m pip install -r requirements-raspberrypi.txt -c numpy-system-constraints.txt
.venv/bin/python -c 'import cv2, numpy, picamera2; print("NumPy:", numpy.__version__, "OpenCV:", cv2.__version__)'
if [[ ! -f config.yaml ]]; then
  cp config.example.yaml config.yaml
fi
.venv/bin/python scripts/download_face_models.py
.venv/bin/python scripts/check_body_model.py
echo 'Instalación terminada. Reinicia si acabas de instalar firmware: sudo reboot'
echo 'Después comprueba la cámara: rpicam-hello --list-cameras'
echo 'Prueba sin hardware: .venv/bin/python main.py --simulate --headless'
