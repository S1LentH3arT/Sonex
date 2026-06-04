import logging
import os
from pathlib import Path


def sonex_home() -> Path:
    custom = os.getenv("SONEX_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex"


def sonex_log_path() -> Path:
    home = sonex_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "log"


def configure_file_logging(level: int = logging.INFO) -> Path:
    log_path = sonex_log_path()
    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.close()
    root_logger.handlers.clear()

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    return log_path


def set_logger(
    name: str = "sonex",
    level: int = logging.INFO,
) -> logging.Logger:
    log_path = sonex_log_path()

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "sonex") -> logging.Logger:
    return logging.getLogger(name)
