"""Genera una unidad para la ruta y el usuario actuales; instalarla es un paso explícito."""

import argparse
import getpass
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Generar la unidad systemd para este equipo.")
    parser.add_argument("--output", type=Path, default=Path("camera-counter.generated.service"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    interpreter = root / ".venv/bin/python"
    if not interpreter.is_file():
        raise SystemExit("Primero crea .venv dentro del proyecto.")
    user = getpass.getuser()
    if user == "root":
        raise SystemExit("Genera la unidad con el usuario habitual, sin sudo.")
    if any(char in str(root) for char in ('"', "%", "\n", "\r", "\\")):
        raise SystemExit("La ruta no debe contener comillas, %, saltos de línea ni barras invertidas.")
    template = (root / "systemd/camera-counter.service").read_text(encoding="utf-8")
    text = template.replace("@USER@", user).replace("@ROOT@", str(root))
    args.output.write_text(text, encoding="utf-8")
    print(f"Unidad generada: {args.output}")
    print("Instálala con los comandos del README.")


if __name__ == "__main__":
    main()
