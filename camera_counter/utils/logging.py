import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


class RedactFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"rtsps?://\S+", "rtsp://[oculta]", record.getMessage(), flags=re.IGNORECASE)
        record.args = ()
        return True


def setup_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(directory / "camera_counter.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"),
    ]
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RedactFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = handlers
