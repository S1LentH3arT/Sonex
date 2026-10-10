"""A small, local-only index of audio files under one user-selected folder."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.log import sonex_home
from src.platform_support import set_private_mode

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".aiff"}
MAX_TRACKS = 500
MAX_DIRECTORIES = 10_000


class MusicLibrary:
    def __init__(self) -> None:
        self.settings = sonex_home() / "music" / "library.json"

    def root(self) -> Path:
        if self.settings.is_symlink():
            raise ValueError("Music library settings cannot be a symbolic link.")
        if not self.settings.exists():
            return Path.home() / "Music"
        value = json.loads(self.settings.read_text(encoding="utf-8"))
        root = Path(value["path"]).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("The music library path must be a folder.")
        return root

    def set_root(self, value: str) -> Path:
        root = Path(value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("The music library path must be a folder.")
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings.with_suffix(".tmp")
        temporary.write_text(json.dumps({"path": str(root)}), encoding="utf-8")
        set_private_mode(temporary, 0o600)
        temporary.replace(self.settings)
        set_private_mode(self.settings, 0o600)
        return root

    def tracks(self) -> dict[str, Any]:
        root = self.root()
        tracks: list[dict[str, str]] = []
        truncated = False
        for directory_count, (directory, subdirectories, names) in enumerate(
            os.walk(root, followlinks=False), start=1
        ):
            if directory_count > MAX_DIRECTORIES:
                truncated = True
                break
            subdirectories[:] = sorted(
                name for name in subdirectories
                if not (Path(directory) / name).is_symlink()
            )
            for name in sorted(names, key=str.casefold):
                path = Path(directory) / name
                if path.suffix.lower() in AUDIO_EXTENSIONS and not path.is_symlink():
                    tracks.append({
                        "path": str(path),
                        "name": path.stem,
                        "title": path.stem,
                        "artist": "",
                        "provider": "local",
                    })
                    if len(tracks) == MAX_TRACKS:
                        truncated = True
                        break
            if truncated:
                break
        return {
            "type": "web_library",
            "path": str(root),
            "tracks": tracks,
            "truncated": truncated,
        }

    def track_path(self, value: str) -> Path:
        root = self.root()
        path = Path(value).expanduser().resolve(strict=True)
        if path.suffix.lower() not in AUDIO_EXTENSIONS or not path.is_file() or not path.is_relative_to(root):
            raise ValueError("Choose an audio file inside the configured music library.")
        return path
