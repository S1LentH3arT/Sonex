"""Pure translation from planner events to runner-facing event payloads."""

from __future__ import annotations

from typing import Any


def runner_event_payload(event: Any) -> dict[str, Any]:
    event_type = str(getattr(event, "type", "") or "")
    if event_type == "status":
        return {"content": event.content}
    if event_type == "tool":
        return {
            "tool_name": event.tool,
            "tool_args": event.args or {},
            "tool_result": event.result,
        }
    if event_type == "tool_batch":
        return {"calls": event.calls or []}
    if event_type in {"tool_approved", "tool_rejected", "tool_blocked"}:
        return {"calls": event.calls or [], **(event.args or {})}
    if event_type in {"error", "complete", "warning"}:
        return {"content": event.content, "tool_name": event.tool}
    return {}
