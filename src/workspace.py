"""Workspace support for sonex application behavior.

Implements the workspace module responsibilities used by Sonex runtime flows.
Key public entry points include WorkspaceBoundaryError, user_workspace_root, ensure_within_user_workspace, user_music_dir.
"""

from __future__ import annotations

from pathlib import Path


class WorkspaceBoundaryError(ValueError):
    """Represents workspace boundary error.

    Encapsulates workspace boundary error data and behavior used by Sonex runtime flows. Extends value error semantics.
    """
    def __init__(self, path: Path, root: Path) -> None:
        """Init for workspace boundary error.

        Coordinates the init method behavior while preserving workspace boundary error state and contracts.

        Args:
            path: Input value used by the init operation.
            root: Input value used by the init operation.
        """
        self.path = path
        self.root = root
        super().__init__(f"Path '{path}' is outside the Sonex user workspace '{root}'.")


def user_workspace_root() -> Path:
    """User workspace root.

    Coordinates user workspace root logic for the surrounding Sonex flow.

    Returns:
        The computed result for user workspace root.
    """
    return Path.home().resolve()


def ensure_within_user_workspace(path: str | Path, *, root: Path | None = None) -> Path:
    """Ensure within user workspace.

    Coordinates ensure within user workspace logic for the surrounding Sonex flow.

    Args:
        path: Input value used by the ensure within user workspace operation.
        root: Input value used by the ensure within user workspace operation.

    Returns:
        The computed result for ensure within user workspace.
    """
    workspace_root = (root or user_workspace_root()).resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve(strict=False)
    if resolved == workspace_root or resolved.is_relative_to(workspace_root):
        return resolved
    raise WorkspaceBoundaryError(resolved, workspace_root)


def user_music_dir() -> Path:
    """User music dir.

    Coordinates user music dir logic for the surrounding Sonex flow.

    Returns:
        The computed result for user music dir.
    """
    return ensure_within_user_workspace(user_workspace_root() / "Music")
