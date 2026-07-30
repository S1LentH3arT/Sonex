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
        """Prepares init for an internal Sonex flow.

        Typical use: Use this helper when nearby code needs init without duplicating the local rules.

        Example: __init__(path=..., root=...) -> returns the value used by the surrounding Sonex flow.
        """
        self.path = path
        self.root = root
        super().__init__(f"Path '{path}' is outside the Sonex user workspace '{root}'.")


def user_workspace_root() -> Path:
    """Coordinates user workspace root for the current Sonex flow.

    Typical use: Use this function when runtime code needs user workspace root as part of a Sonex command, playback, auth, llm, or ui path.

    Example: user_workspace_root() -> returns the value used by the surrounding Sonex flow.
    """
    return Path.home().resolve()


def ensure_within_user_workspace(path: str | Path, *, root: Path | None = None) -> Path:
    """Coordinates ensure within user workspace for the current Sonex flow.

    Typical use: Use this function when runtime code needs ensure within user workspace as part of a Sonex command, playback, auth, llm, or ui path.

    Example: ensure_within_user_workspace(path=..., root=...) -> returns the value used by the surrounding Sonex flow.
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
    """Coordinates user music dir for the current Sonex flow.

    Typical use: Use this function when runtime code needs user music dir as part of a Sonex command, playback, auth, llm, or ui path.

    Example: user_music_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return ensure_within_user_workspace(user_workspace_root() / "Music")
