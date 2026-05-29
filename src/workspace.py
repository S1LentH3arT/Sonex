from __future__ import annotations

from pathlib import Path


class WorkspaceBoundaryError(ValueError):
    def __init__(self, path: Path, root: Path) -> None:
        self.path = path
        self.root = root
        super().__init__(f"Path '{path}' is outside the Sonex user workspace '{root}'.")


def user_workspace_root() -> Path:
    return Path.home().resolve()


def ensure_within_user_workspace(path: str | Path, *, root: Path | None = None) -> Path:
    workspace_root = (root or user_workspace_root()).resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve(strict=False)
    if resolved == workspace_root or resolved.is_relative_to(workspace_root):
        return resolved
    raise WorkspaceBoundaryError(resolved, workspace_root)


def user_music_dir() -> Path:
    return ensure_within_user_workspace(user_workspace_root() / "Music")
