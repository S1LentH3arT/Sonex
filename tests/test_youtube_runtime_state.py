"""Tests for pure managed-runtime state transitions."""

from __future__ import annotations

from src.tools.youtube_runtime_state import (
    activated_state,
    cache_is_fresh,
    component_install_state,
    health_check_state,
    health_update_action,
    lock_busy_message,
    managed_runtime_failure_code,
    provider_failure_category,
    probation_failed,
    probation_succeeded,
    provider_idle_action,
    provider_log_action,
    provider_reuse_allowed,
    provider_exit_reason,
    provider_startup_action,
    request_gate_wait_seconds,
    runtime_manifest_is_usable,
    is_newer_version,
    same_major_version,
    version_tuple,
    provider_runtime_status,
    restart_notice,
    rollback_state,
    runtime_status_value,
    update_failure_state,
    update_start_action,
    update_completion_state,
)


def test_activation_and_rollback_states_preserve_runtime_identity() -> None:
    candidate = {"runtime_id": "candidate", "yt_dlp_version": "2026.08.19", "provider_version": "1.3.2"}

    assert activated_state(candidate, 10.0) == {
        "status": "ready",
        "runtime_id": "candidate",
        "yt_dlp_version": "2026.08.19",
        "provider_version": "1.3.2",
        "activated_at": 10.0,
        "probation": True,
    }
    assert rollback_state({"runtime_id": "previous"}, 20.0) == {
        "status": "ready",
        "runtime_id": "previous",
        "rollback_applied_at": 20.0,
        "probation": False,
    }


def test_probation_transitions_are_terminal_and_bounded() -> None:
    state = {"status": "ready", "probation": True}

    assert probation_succeeded(state, "candidate", 30.0)["probation"] is False
    failed = probation_failed(state, "x" * 200)
    assert failed["status"] == "degraded"
    assert failed["rollback_pending"] is True
    assert len(failed["rollback_reason"]) == 160


def test_runtime_status_precedence_is_fail_closed() -> None:
    manifest = {"runtime_id": "active"}

    assert runtime_status_value(None, {}, {"runtime_id": "pending"}) == "setup_required"
    assert runtime_status_value(manifest, {"status": "degraded"}, {"runtime_id": "pending"}) == "degraded"
    assert runtime_status_value(manifest, {"status": "ready"}, {"runtime_id": "pending"}) == "restart_required"
    assert runtime_status_value(manifest, {"status": "ready"}, None) == "ready"


def test_component_install_state_prefers_update_progress_then_local_error() -> None:
    assert component_install_state(
        "node",
        installed=False,
        error="missing dependency",
        update={"status": "running", "component": "node", "progress": 0.4},
    ) == ("installing", 0.4, None)
    assert component_install_state(
        "node",
        installed=True,
        error=None,
        update={"status": "failed", "component": "node"},
    ) == ("failed", None, None)
    assert component_install_state(
        "node",
        installed=False,
        error="missing dependency",
        update={"status": "idle"},
    ) == ("failed", None, "missing dependency")


def test_health_check_state_respects_missing_runtime_and_rollback() -> None:
    manifest = {"runtime_id": "active"}
    healthy = {"healthy": True, "reason": "ok"}
    broken = {"healthy": False, "reason": "runtime_files_missing"}

    assert health_check_state(None, healthy, rollback_pending=False)["status"] == "setup_required"
    assert health_check_state(manifest, healthy, rollback_pending=False) == {
        "status": "ready",
        "local_check": healthy,
    }
    assert health_check_state(manifest, broken, rollback_pending=False)["status"] == "degraded"
    assert health_check_state(manifest, healthy, rollback_pending=True)["status"] == "degraded"


def test_health_update_action_blocks_duplicate_jobs_and_gates_major_changes() -> None:
    base = {
        "manifest_present": True,
        "pending_present": False,
        "update_status": "idle",
        "update_phase": "",
        "provider_update": False,
        "yt_update": False,
        "provider_major_compatible": True,
    }

    assert health_update_action(**base) is None
    assert health_update_action(**(base | {"update_status": "running", "yt_update": True})) is None
    assert health_update_action(**(base | {"provider_update": True, "provider_major_compatible": False})) == "major_update_requires_consent"
    assert health_update_action(**(base | {"yt_update": True})) == "update"


def test_update_start_action_enforces_worker_and_retry_cooldown_guards() -> None:
    assert update_start_action(
        {"status": "running", "retry_after": 999},
        now=100,
        force=False,
        worker_alive=True,
    ) == "already_running"
    assert update_start_action(
        {"status": "failed", "retry_after": 999},
        now=100,
        force=False,
        worker_alive=False,
    ) == "cooldown"
    assert update_start_action(
        {"status": "failed", "retry_after": 999},
        now=100,
        force=True,
        worker_alive=False,
    ) == "start"
    assert update_start_action(
        {"status": "failed", "retry_after": "invalid"},
        now=100,
        force=False,
        worker_alive=False,
    ) == "start"


def test_update_failure_state_keeps_cooldown_and_optional_worker_details() -> None:
    assert update_failure_state(
        phase="spawn_failed",
        error="OSError",
        retry_after=200,
    ) == {
        "status": "failed",
        "phase": "spawn_failed",
        "error": "OSError",
        "retry_after": 200,
    }
    assert update_failure_state(
        phase="failed",
        error="TimeoutError",
        retry_after=200,
        completed_at=150,
        elapsed_seconds=3.5,
        component="node",
    )["component"] == "node"


def test_provider_runtime_status_requires_process_and_optional_probe_health() -> None:
    provider = {"base_url": "http://127.0.0.1:45231"}

    assert provider_runtime_status(
        None,
        process_alive=True,
        ping_healthy=True,
        probe=True,
    ) == "stopped"
    assert provider_runtime_status(
        provider,
        process_alive=False,
        ping_healthy=True,
        probe=True,
    ) == "stopped"
    assert provider_runtime_status(
        provider,
        process_alive=True,
        ping_healthy=False,
        probe=True,
    ) == "stopped"
    assert provider_runtime_status(
        provider,
        process_alive=True,
        ping_healthy=None,
        probe=False,
    ) == "running"


def test_provider_reuse_requires_active_runtime_identity() -> None:
    provider = {"runtime_id": "active"}
    common = {"process_alive": True, "ping_healthy": True}

    assert provider_reuse_allowed(provider, runtime_id="active", **common)
    assert not provider_reuse_allowed(provider, runtime_id="stale", **common)
    assert not provider_reuse_allowed(provider, runtime_id="active", process_alive=False, ping_healthy=True)
    assert not provider_reuse_allowed(provider, runtime_id="active", process_alive=True, ping_healthy=False)


def test_provider_idle_action_handles_missing_expired_and_invalid_timestamps() -> None:
    assert provider_idle_action({}, now=100, idle_seconds=60) == "keep"
    assert provider_idle_action({"last_activity_at": 50}, now=100, idle_seconds=60) == "keep"
    assert provider_idle_action({"last_activity_at": 40}, now=100, idle_seconds=60) == "stop"
    assert provider_idle_action({"last_activity_at": "invalid"}, now=100, idle_seconds=60) == "stop"


def test_provider_startup_action_distinguishes_ready_wait_and_failure() -> None:
    assert provider_startup_action(process_alive=True, ping_healthy=True, deadline_reached=False) == "ready"
    assert provider_startup_action(process_alive=True, ping_healthy=False, deadline_reached=False) == "wait"
    assert provider_startup_action(process_alive=False, ping_healthy=False, deadline_reached=False) == "failed"
    assert provider_startup_action(process_alive=True, ping_healthy=False, deadline_reached=True) == "failed"


def test_provider_exit_reason_distinguishes_idle_state_and_child_outcomes() -> None:
    assert provider_exit_reason(idle_expired=True, state_present=True, returncode=-15) == "idle_timeout"
    assert provider_exit_reason(idle_expired=False, state_present=False, returncode=1) == "state_removed"
    assert provider_exit_reason(idle_expired=False, state_present=True, returncode=None) == "monitor_stopped"
    assert provider_exit_reason(idle_expired=False, state_present=True, returncode=0) == "child_exit"
    assert provider_exit_reason(idle_expired=False, state_present=True, returncode=1) == "child_exit_failed"


def test_provider_log_action_rotates_only_above_the_size_limit() -> None:
    assert provider_log_action(file_size=1024, max_bytes=1024) == "keep"
    assert provider_log_action(file_size=1025, max_bytes=1024) == "rotate"


def test_request_gate_wait_seconds_clamps_interval_and_timeout() -> None:
    assert request_gate_wait_seconds(
        last_started_at=100,
        now=105,
        min_interval=3,
        timeout=75,
    ) == 0
    assert request_gate_wait_seconds(
        last_started_at=100,
        now=100,
        min_interval=3,
        timeout=75,
    ) == 3
    assert request_gate_wait_seconds(
        last_started_at=100,
        now=100,
        min_interval=10,
        timeout=2,
    ) == 2
    assert request_gate_wait_seconds(
        last_started_at="invalid",
        now=100,
        min_interval=3,
        timeout=75,
    ) == 0


def test_lock_busy_message_distinguishes_provider_and_request_scopes() -> None:
    assert lock_busy_message("provider") == "YouTube provider is busy; try again later."
    assert lock_busy_message("request") == "YouTube request queue is busy; try again later."


def test_managed_runtime_failure_code_precedes_generic_error_fallbacks() -> None:
    assert managed_runtime_failure_code("YOUTUBE_QUEUE_BUSY") == "youtube_queue_busy"
    assert managed_runtime_failure_code("YouTube PO Token Provider is unavailable") == "youtube_po_provider_unavailable"
    assert managed_runtime_failure_code(RuntimeError("network timeout")) is None


def test_provider_failure_category_applies_stable_precedence() -> None:
    assert provider_failure_category(
        managed_code="youtube_queue_busy",
        timed_out=True,
        rate_limited=True,
        age_restricted=True,
        bot_challenge=True,
        unavailable=True,
    ) == "youtube_queue_busy"
    assert provider_failure_category(
        managed_code=None,
        timed_out=True,
        rate_limited=True,
        age_restricted=False,
        bot_challenge=False,
        unavailable=False,
    ) == "provider_timeout"
    assert provider_failure_category(
        managed_code=None,
        timed_out=False,
        rate_limited=False,
        age_restricted=False,
        bot_challenge=True,
        unavailable=True,
    ) == "provider_bot_challenge"
    assert provider_failure_category(
        managed_code=None,
        timed_out=False,
        rate_limited=False,
        age_restricted=False,
        bot_challenge=False,
        unavailable=False,
    ) == "provider_error"


def test_version_policy_handles_numeric_segments_and_major_compatibility() -> None:
    assert version_tuple("2026.08.19") == (2026, 8, 19)
    assert version_tuple("1.3rc2") == (1, 32)
    assert version_tuple("invalid") == ()
    assert is_newer_version("1.4.0", "1.3.2")
    assert not is_newer_version("1.3.2", "1.3.2")
    assert same_major_version("1.4.0", "1.3.2")
    assert not same_major_version("2.0.0", "1.9.9")


def test_runtime_manifest_requires_format_identity_and_executable_paths() -> None:
    manifest = {
        "format": 1,
        "runtime_id": "runtime",
        "bundle_path": "/bundle",
        "python_executable": "/bundle/python",
        "server_entry": "/bundle/server.js",
    }
    assert runtime_manifest_is_usable(manifest, runtime_format=1)
    assert not runtime_manifest_is_usable(manifest | {"format": 2}, runtime_format=1)
    assert not runtime_manifest_is_usable(manifest | {"format": "invalid"}, runtime_format=1)
    assert not runtime_manifest_is_usable(manifest | {"server_entry": ""}, runtime_format=1)
    assert not runtime_manifest_is_usable({"format": 1}, runtime_format=1)


def test_cache_is_fresh_fails_closed_for_invalid_or_expired_metadata() -> None:
    assert cache_is_fresh({"checked_at": 90}, now=100, ttl=20)
    assert not cache_is_fresh({"checked_at": 70}, now=100, ttl=20)
    assert not cache_is_fresh({"checked_at": "invalid"}, now=100, ttl=20)
    assert not cache_is_fresh(None, now=100, ttl=20)


def test_update_completion_and_restart_notice_share_one_state_contract() -> None:
    manifest = {"runtime_id": "candidate"}

    assert update_completion_state(manifest) == {
        "status": "ready",
        "phase": "restart_required",
        "candidate_runtime_id": "candidate",
        "restart_required": True,
    }
    assert update_completion_state(None)["phase"] == "component_complete"
    assert restart_notice({"phase": "component_complete"}) is None
    assert restart_notice({"phase": "restart_required", "restart_required": True}) == (
        "YouTube runtime update ready · setup → new\nRestart Sonex to apply."
    )
