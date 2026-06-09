"""Config support for runtime logging configuration.

Implements the config module responsibilities used by Sonex runtime flows.
Key public entry points include sonex_home, sonex_log_path, configure_file_logging, set_logger, get_logger.
"""

import logging
import os
from pathlib import Path


def sonex_home() -> Path:
    """Sonex home.

    Coordinates sonex home logic for the surrounding Sonex flow.

    Returns:
        The computed result for sonex home.
    """
    custom = os.getenv("SONEX_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex"


def sonex_log_path() -> Path:
    """Sonex log path.

    Coordinates sonex log path logic for the surrounding Sonex flow.

    Returns:
        The computed result for sonex log path.
    """
    home = sonex_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "log"


def configure_file_logging(level: int = logging.INFO) -> Path:
    """Configure file logging.

    Coordinates configure file logging logic for the surrounding Sonex flow.

    Args:
        level: Input value used by the configure file logging operation.

    Returns:
        The computed result for configure file logging.
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
    """Set logger.

    Coordinates set logger logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the set logger operation.
        level: Input value used by the set logger operation.

    Returns:
        The computed result for set logger.
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
    """Get logger.

    Coordinates get logger logic for the surrounding Sonex flow.

    Args:
        name: Input value used by the get logger operation.

    Returns:
        The computed result for get logger.
    """
    return logging.getLogger(name)
