import logging
import os
from pathlib import Path


def sonex_home() -> Path:
    custom = os.getenv("SONEX_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex"


def set_logger(
        name: str = "sonex",
        level: int = logging.INFO,
) -> logging.Logger:
    log_dir = sonex_home() / "sonex.log"

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_dir)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "sonex") -> logging.Logger:
    return logging.getLogger(name)