"""Child-process entry point for one bounded yt-dlp operation."""

from __future__ import annotations

import json
import sys
from typing import Any

import yt_dlp


def _respond(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
    return exit_code


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("yt-dlp worker request must be an object")
        operation = str(request.get("operation") or "")
        target = str(request.get("target") or "")
        options = request.get("options")
        if operation not in {"search", "resolve", "download"}:
            raise ValueError(f"Unsupported yt-dlp operation: {operation}")
        if not target or not isinstance(options, dict):
            raise ValueError("yt-dlp worker request is incomplete")
        if operation == "download":
            def progress_hook(status: dict[str, Any]) -> None:
                if status.get("status") in {"downloading", "finished"}:
                    sys.stderr.write("SONEX_PROGRESS\n")
                    sys.stderr.flush()

            sys.stderr.write("SONEX_PROGRESS\n")
            sys.stderr.flush()
            options = dict(options)
            options["progress_hooks"] = [progress_hook]
        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.extract_info(target, download=operation == "download")
        if not isinstance(result, dict):
            raise ValueError("yt-dlp returned a non-object result")
        return _respond({"ok": True, "result": result})
    except Exception as exc:
        return _respond(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            exit_code=1,
        )


if __name__ == "__main__":
    raise SystemExit(main())
