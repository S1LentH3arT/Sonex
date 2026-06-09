"""Config support for runtime logging configuration.

Implements the config module responsibilities used by Sonex runtime flows.
Key public entry points include sonex_home, sonex_log_path, configure_file_logging, set_logger, get_logger.
"""

import logging
import os
from pathlib import Path


def sonex_home() -> Path:
    """Coordinates sonex home for the current Sonex flow.

    Typical use: Use this function when runtime code needs sonex home as part of a Sonex command, playback, auth, llm, or ui path.

    Example: sonex_home() -> returns the value used by the surrounding Sonex flow.
    """
    custom = os.getenv("SONEX_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex"


def sonex_log_path() -> Path:
    """Coordinates sonex log path for the current Sonex flow.

    Typical use: Use this function when runtime code needs sonex log path as part of a Sonex command, playback, auth, llm, or ui path.

    Example: sonex_log_path() -> returns the value used by the surrounding Sonex flow.
    """
    home = sonex_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "log"


def configure_file_logging(level: int = logging.INFO) -> Path:
    """Coordinates configure file logging for the current Sonex flow.

    Typical use: Use this function when runtime code needs configure file logging as part of a Sonex command, playback, auth, llm, or ui path.

    Example: configure_file_logging(level=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Coordinates set logger for the current Sonex flow.

    Typical use: Use this function when runtime code needs set logger as part of a Sonex command, playback, auth, llm, or ui path.

    Example: set_logger(name=..., level=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Returns logger for the current Sonex flow.

    Typical use: Use this function when runtime code needs get logger as part of a Sonex command, playback, auth, llm, or ui path.

    Example: get_logger(name=...) -> returns the value used by the surrounding Sonex flow.
    """
    return logging.getLogger(name)
