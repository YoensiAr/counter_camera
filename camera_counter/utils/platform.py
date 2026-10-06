import platform
from pathlib import Path


def is_raspberry_pi() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        return "raspberry pi" in Path("/proc/device-tree/model").read_text().lower()
    except OSError:
        return False


def platform_details() -> dict:
    return {
        "os": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "raspberry_pi": is_raspberry_pi(),
    }
