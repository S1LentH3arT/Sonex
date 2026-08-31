"""Built-in music extension registry and lifecycle state.

The registry is intentionally small and application-owned.  It describes the
four providers exposed by the TUI while leaving credentials and provider
implementations in their existing modules.
"""

from .manager import (
    ExtensionActionError,
    ExtensionManager,
    ExtensionStatus,
    ExtensionView,
    builtin_extensions,
)

__all__ = [
    "ExtensionActionError",
    "ExtensionManager",
    "ExtensionStatus",
    "ExtensionView",
    "builtin_extensions",
]
