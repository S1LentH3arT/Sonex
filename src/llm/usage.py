"""Session-scoped token usage observation for LLM requests."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Callable

from src.llm.transport.base import Usage

logger = logging.getLogger(__name__)

TokenUsageObserver = Callable[[Usage], None]

_token_usage_observer: ContextVar[TokenUsageObserver | None] = ContextVar(
    "sonex_token_usage_observer",
    default=None,
)


def set_token_usage_observer(observer: TokenUsageObserver) -> Token[TokenUsageObserver | None]:
    """Bind an LLM usage observer to the current execution context."""
    return _token_usage_observer.set(observer)


def reset_token_usage_observer(token: Token[TokenUsageObserver | None]) -> None:
    """Restore the observer that preceded ``token``."""
    _token_usage_observer.reset(token)


def report_token_usage(usage: Usage) -> None:
    """Report normalized provider usage without affecting the model response path."""
    observer = _token_usage_observer.get()
    if observer is None:
        return
    try:
        observer(usage)
    except Exception:
        logger.warning("Token usage observer failed.", exc_info=True)
