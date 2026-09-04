"""Pure state transitions for the managed YouTube runtime."""

from __future__ import annotations

from typing import Any


def version_tuple(value: Any) -> tuple[int, ...]:
    """Parse numeric version segments for deterministic comparisons."""
    parts: list[int] = []
    for part in str(value or "").split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer_version(candidate: Any, current: Any) -> bool:
    left = version_tuple(candidate)
    right = version_tuple(current)
    return bool(left and right and left > right)


def same_major_version(candidate: Any, current: Any) -> bool:
    left = version_tuple(candidate)
    right = version_tuple(current)
    return bool(left and right and left[0] == right[0])


def runtime_manifest_is_usable(payload: Any, *, runtime_format: int) -> bool:
    """Require the identity and executable paths needed by managed runtime."""
    if not isinstance(payload, dict):
        return False
    try:
        format_value = int(payload.get("format") or 0)
    except (TypeError, ValueError):
        return False
    if format_value != runtime_format:
        return False
    return all(
        str(payload.get(key) or "").strip()
        for key in ("runtime_id", "bundle_path", "python_executable", "server_entry")
    )


def cache_is_fresh(payload: Any, *, now: float, ttl: float) -> bool:
    """Treat malformed or expired persisted cache metadata as stale."""
    if not isinstance(payload, dict):
        return False
    try:
        checked_at = float(payload.get("checked_at") or 0)
    except (TypeError, ValueError):
        return False
    return now - checked_at < ttl


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


def provider_runtime_status(
    provider: dict[str, Any] | None,
    *,
    process_alive: bool,
    ping_healthy: bool | None,
    probe: bool,
) -> str:
    """Resolve provider liveness without conflating process and HTTP health."""
    if not provider or not process_alive:
        return "stopped"
    if probe and not ping_healthy:
        return "stopped"
    return "running"


def provider_reuse_allowed(
    provider: dict[str, Any] | None,
    *,
    runtime_id: Any,
    process_alive: bool,
    ping_healthy: bool,
) -> bool:
    """Allow reuse only for a healthy provider bound to the active runtime."""
    return bool(
        provider
        and provider.get("runtime_id") == runtime_id
        and process_alive
        and ping_healthy
    )


def provider_idle_action(
    state: dict[str, Any],
    *,
    now: float,
    idle_seconds: float,
) -> str:
    """Resolve whether the detached provider should remain alive."""
    raw_last_activity = state.get("last_activity_at")
    if raw_last_activity in (None, ""):
        return "keep"
    try:
        last_activity = float(raw_last_activity)
    except (TypeError, ValueError):
        return "stop"
    return "stop" if now - last_activity >= idle_seconds else "keep"


def provider_startup_action(
    *,
    process_alive: bool,
    ping_healthy: bool,
    deadline_reached: bool,
) -> str:
    """Resolve the detached provider startup probe transition."""
    if ping_healthy:
        return "ready"
    if deadline_reached or not process_alive:
        return "failed"
    return "wait"


def provider_exit_reason(
    *,
    idle_expired: bool,
    state_present: bool,
    returncode: int | None,
) -> str:
    """Classify why the detached provider monitor stopped."""
    if idle_expired:
        return "idle_timeout"
    if not state_present:
        return "state_removed"
    if returncode is None:
        return "monitor_stopped"
    return "child_exit" if returncode == 0 else "child_exit_failed"


def provider_log_action(*, file_size: int, max_bytes: int) -> str:
    """Resolve whether the provider log should rotate before opening."""
    return "rotate" if file_size > max_bytes else "keep"


def request_gate_wait_seconds(
    *,
    last_started_at: Any,
    now: float,
    min_interval: float,
    timeout: float,
) -> float:
    """Bound per-egress pacing without extending the caller's timeout."""
    try:
        last_started = float(last_started_at or 0.0)
    except (TypeError, ValueError):
        last_started = 0.0
    wait_for = min_interval - (now - last_started)
    return min(wait_for, max(0.01, timeout)) if wait_for > 0 else 0.0


def lock_busy_message(purpose: str) -> str:
    """Return the user-facing message for a bounded lock timeout."""
    if purpose == "provider":
        return "YouTube provider is busy; try again later."
    return "YouTube request queue is busy; try again later."


def managed_runtime_failure_code(value: Any) -> str | None:
    """Classify stable managed-runtime failures before generic fallbacks."""
    code = getattr(value, "code", None)
    text = str(code or value or "").casefold()
    if text == "youtube_po_provider_unavailable" or "po token provider" in text:
        return "youtube_po_provider_unavailable"
    if text == "youtube_queue_busy" or "request queue is busy" in text or "youtube provider is busy" in text:
        return "youtube_queue_busy"
    return None


def provider_failure_category(
    *,
    managed_code: str | None,
    timed_out: bool,
    rate_limited: bool,
    age_restricted: bool,
    bot_challenge: bool,
    unavailable: bool,
) -> str:
    """Apply one precedence table to provider failure facts."""
    if managed_code:
        return managed_code
    if timed_out:
        return "provider_timeout"
    if rate_limited:
        return "provider_rate_limited"
    if age_restricted:
        return "candidate_unplayable"
    if bot_challenge:
        return "provider_bot_challenge"
    if unavailable:
        return "candidate_unplayable"
    return "provider_error"


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
