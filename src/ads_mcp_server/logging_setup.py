"""Daily file logging."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"


def get_logger(name: str = "ads_mcp_server") -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_path = LOG_DIR / f"{date.today().isoformat()}.log"
    handler = logging.FileHandler(log_path)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    logger.addHandler(handler)
    return logger
