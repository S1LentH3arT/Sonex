"""Trusted System Tools backed by the controlled NetEase Provider Worker."""

from __future__ import annotations

from typing import Any

from src.music.netease_worker import NetEaseProviderWorker
from src.tools.registry import Params, registry
from src.tools.result import ToolResult


_worker = NetEaseProviderWorker()


def netease_account() -> dict[str, Any]:
    health = _worker.health()
    return ToolResult.success(
        tool="netease_account",
        message="NetEase Provider Worker health loaded.",
        data={
            "logged_in": health.login_ready,
            "ready": health.ready,
            "version": health.version,
            "player": "ncm-cli/mpv",
            "verification": "unverified_playback",
            "reason": health.reason,
        },
    ).to_dict()


def netease_search(query: str, limit: int = 10) -> dict[str, Any]:
    try:
        songs = _worker.search(query, limit=limit)
    except Exception as exc:
        return ToolResult.fail(
            tool="netease_search",
            message=str(exc),
            error_code="NETEASE_SEARCH_FAILED",
            data={"provider": "netease"},
        ).to_dict()
    return ToolResult.success(
        tool="netease_search",
        message=f"Loaded {len(songs)} NetEase track(s).",
        data={"tracks": songs, "provider": "netease"},
    ).to_dict()


def netease_play(encrypted_id: str, original_id: str) -> dict[str, Any]:
    try:
        data = _worker.play(
            encrypted_id=encrypted_id,
            original_id=original_id,
        )
    except Exception as exc:
        return ToolResult.fail(
            tool="netease_play",
            message=str(exc),
            error_code="NETEASE_PLAYBACK_FAILED",
            data={"provider": "netease"},
        ).to_dict()
    return ToolResult.success(
        tool="netease_play",
        message="NetEase playback started.",
        data=data,
    ).to_dict()


def _register(
    name: str,
    fn: Any,
    *,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    read_only: bool,
) -> None:
    registry.register(
        name=name,
        kind="system",
        domain="netease",
        description=f"Controlled NetEase Provider Worker operation: {name}.",
        parameters=Params(
            type="object",
            properties=properties or {},
            required=required or [],
        ),
        fn=fn,
        enable=True,
        read_only=read_only,
        required_confirm=False,
    )


_register("netease_account", netease_account, read_only=True)
_register(
    "netease_search",
    netease_search,
    properties={
        "query": {"type": "string"},
        "limit": {"type": "integer"},
    },
    required=["query"],
    read_only=True,
)
_register(
    "netease_play",
    netease_play,
    properties={
        "encrypted_id": {"type": "string"},
        "original_id": {"type": "string"},
    },
    required=["encrypted_id", "original_id"],
    read_only=False,
)
