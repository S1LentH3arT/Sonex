"""Tests for pure managed-runtime state transitions."""

from __future__ import annotations

from src.tools.youtube_runtime_state import (
    activated_state,
    component_install_state,
    health_check_state,
    health_update_action,
    probation_failed,
    probation_succeeded,
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
