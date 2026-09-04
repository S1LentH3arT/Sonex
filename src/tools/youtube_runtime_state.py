"""Pure state transitions for the managed YouTube runtime."""

from __future__ import annotations

from typing import Any


def runtime_status_value(
    manifest: dict[str, Any] | None,
    state: dict[str, Any],
    pending: dict[str, Any] | None,
) -> str:
    """Resolve the externally visible runtime status by precedence."""
    if not manifest:
        return "setup_required"
    if state.get("status") == "degraded":
        return "degraded"
    if pending:
        return "restart_required"
    return str(state.get("status") or "ready")


def health_check_state(
    manifest: dict[str, Any] | None,
    local_check: dict[str, Any],
    *,
    rollback_pending: bool,
) -> dict[str, Any]:
    if not manifest:
        status = "setup_required"
    elif local_check.get("healthy"):
        status = "ready"
    else:
        status = "degraded"
    if rollback_pending:
        status = "degraded"
    return {"status": status, "local_check": local_check}


def health_update_action(
    *,
    manifest_present: bool,
    pending_present: bool,
    update_status: str,
    update_phase: str,
    provider_update: bool,
    yt_update: bool,
    provider_major_compatible: bool,
) -> str | None:
    """Return the next update action after a successful health check."""
    if not manifest_present or pending_present:
        return None
    if update_status == "running" or (
        update_status == "ready" and update_phase == "restart_required"
    ):
        return None
    if provider_update and not provider_major_compatible:
        return "major_update_requires_consent"
    if provider_update or yt_update:
        return "update"
    return None


def update_start_action(
    state: dict[str, Any],
    *,
    now: float,
    force: bool,
    worker_alive: bool,
) -> str:
    """Resolve whether an update may start, is running, or is cooling down."""
    if state.get("status") == "running" and worker_alive:
        return "already_running"
    if not force:
        try:
            retry_after = float(state.get("retry_after") or 0)
        except (TypeError, ValueError):
            retry_after = 0
        if retry_after > now:
            return "cooldown"
    return "start"


def update_failure_state(
    *,
    phase: str,
    error: str,
    retry_after: float,
    completed_at: float | None = None,
    elapsed_seconds: float | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    """Build one fail-closed update state with a retry cooldown."""
    state: dict[str, Any] = {
        "status": "failed",
        "phase": phase,
        "error": error,
        "retry_after": retry_after,
    }
    if completed_at is not None:
        state["completed_at"] = completed_at
    if elapsed_seconds is not None:
        state["elapsed_seconds"] = elapsed_seconds
    if component is not None:
        state["component"] = component
    return state


def component_install_state(
    component: str,
    *,
    installed: bool,
    error: str | None,
    update: dict[str, Any],
) -> tuple[str, Any, str | None]:
    """Merge persisted update progress with the component's local check."""
    if update.get("status") == "running" and str(update.get("component") or "") == component:
        return "installing", update.get("progress"), None
    if update.get("status") == "failed" and str(update.get("component") or "") == component:
        return "failed", None, None
    return ("installed" if installed else "failed" if error else "missing"), None, error


def update_completion_state(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if manifest:
        return {
            "status": "ready",
            "phase": "restart_required",
            "candidate_runtime_id": manifest.get("runtime_id"),
            "restart_required": True,
        }
    return {
        "status": "ready",
        "phase": "component_complete",
        "restart_required": False,
    }


def restart_notice(state: dict[str, Any]) -> str | None:
    if state.get("phase") != "restart_required" or not state.get("restart_required"):
        return None
    return (
        f"YouTube runtime update ready · {state.get('previous_yt_dlp_version') or 'setup'} "
        f"→ {state.get('candidate_yt_dlp_version') or 'new'}\nRestart Sonex to apply."
    )


def activated_state(candidate: dict[str, Any], now: float) -> dict[str, Any]:
    return {
        "status": "ready",
        "runtime_id": candidate.get("runtime_id"),
        "yt_dlp_version": candidate.get("yt_dlp_version"),
        "provider_version": candidate.get("provider_version"),
        "activated_at": now,
        "probation": True,
    }


def rollback_state(previous: dict[str, Any] | None, now: float) -> dict[str, Any]:
    return {
        "status": "ready" if previous else "setup_required",
        "runtime_id": (previous or {}).get("runtime_id"),
        "rollback_applied_at": now,
        "probation": False,
    }


def probation_succeeded(state: dict[str, Any], runtime_id: Any, now: float) -> dict[str, Any]:
    return {
        **state,
        "status": "ready",
        "probation": False,
        "known_good_runtime_id": runtime_id,
        "last_success_at": now,
    }


def probation_failed(state: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **state,
        "status": "degraded",
        "rollback_pending": True,
        "rollback_reason": str(reason)[:160],
        "probation": False,
    }
