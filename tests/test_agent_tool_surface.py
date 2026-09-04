"""Contracts for the small model-callable Sonex tool surface."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from src.sandbox.guardrail import inspect_script
from src.agent.interactions import (
    clear_interrupted_interaction,
    has_interrupted_interaction,
    mark_interrupted_interaction,
)
from src.sandbox.manager import SandboxManager, SandboxReport, SandboxState
from src.sandbox.tool import (
    register_bash_tool,
    sandbox_manager,
    set_sandbox_manager_for_tests,
)
from src.extensions import ExtensionStatus
from src.tools.agent_surface import (
    Call,
    Recommend,
    Query,
    Workflow,
    WorkflowRegistry,
    remember_local_track,
)
from src.tools.registry import Params, ToolRegistry


def _register(
    tools: ToolRegistry,
    *,
    name: str,
    kind: str,
    availability=None,
) -> None:
    tools.register(
        name=name,
        kind=kind,
        domain="test",
        description="test",
        parameters=Params(type="object", properties={}, required=[]),
        fn=lambda: name,
        availability=availability,
        confirm_required=False,
    )


def test_registry_requires_explicit_kind_and_domain() -> None:
    tools = ToolRegistry()
    with pytest.raises(TypeError, match="kind.*domain"):
        tools.register(
            name="unsafe",
            description="missing classification",
            parameters=Params(type="object", properties={}, required=[]),
            fn=lambda: None,
        )


def test_registry_separates_schemas_and_invocation_gateways() -> None:
    tools = ToolRegistry()
    _register(tools, name="system_one", kind="system")
    _register(tools, name="agent_one", kind="agent")

    assert [item["function"]["name"] for item in tools.agent_schemas()] == ["agent_one"]
    assert tools.invoke_system("system_one") == "system_one"
    assert tools.invoke_agent("agent_one") == "agent_one"
    with pytest.raises(ValueError, match="Agent Tool"):
        tools.invoke_agent("system_one")
    with pytest.raises(ValueError, match="System Tool"):
        tools.invoke_system("agent_one")
    assert tools.invoke("system_one") == "system_one"
    with pytest.raises(ValueError, match="System Tool"):
        tools.invoke("agent_one")


def test_agent_schema_honors_dynamic_availability() -> None:
    tools = ToolRegistry()
    ready = False
    _register(tools, name="Bash", kind="agent", availability=lambda: ready)
    assert tools.agent_schemas() == []
    ready = True
    assert [item["function"]["name"] for item in tools.agent_schemas()] == ["Bash"]


def test_bash_schema_exposes_reviewable_command_array_only(tmp_path: Path) -> None:
    tools = ToolRegistry()
    manager = SandboxManager(root=tmp_path / "sandbox")
    original = sandbox_manager()
    try:
        with patch.object(manager, "ready", return_value=True):
            set_sandbox_manager_for_tests(manager)
            register_bash_tool(tools)
            schema = tools.agent_schemas()[0]["function"]
    finally:
        set_sandbox_manager_for_tests(original)

    properties = schema["parameters"]["properties"]
    assert schema["parameters"]["required"] == ["commands"]
    assert properties["commands"]["type"] == "array"
    assert properties["commands"]["maxItems"] == 12
    assert "script" not in properties
    assert "cwd" not in properties


def test_workflow_registry_never_resolves_dynamic_function_names() -> None:
    workflows = WorkflowRegistry()
    workflows.register(Workflow("playback.select", lambda args: {"args": args}))

    assert workflows.invoke("playback.select", {"query": "Blue"}) == {
        "args": {"query": "Blue"}
    }
    denied = workflows.invoke("src.tools.spotify_play.spotify_play", {})
    assert denied["error_code"] == "WORKFLOW_NOT_ALLOWED"


def test_call_selection_is_structured_and_does_not_play() -> None:
    result = Call("playback.select", {"query": "Blue in Green"})

    assert result["status"] == "requires_play_selection"
    assert result["data"]["workflow"] == "playback.select"
    assert result["data"]["timeout_seconds"] == 60


def test_local_track_reference_is_opaque_and_resolvable_by_call() -> None:
    local_path = "/home/example/Music/private/song.mp3"
    ref = remember_local_track(local_path)

    assert local_path not in ref
    assert ref.startswith("local:track:")
    with patch("src.tools.agent_surface.registry.invoke_system") as invoke:
        invoke.return_value = {"status": "success"}
        result = Call("playback.play", {"provider": "local", "ref": ref})

    assert result["status"] == "success"
    invoke.assert_called_once_with(
        "play_local_song",
        {"query": local_path, "player": "auto"},
    )


def test_extension_surface_rejects_unregistered_provider() -> None:
    query = Query("apple_music", "catalog", "Song")
    assert query["status"] == "fail"
    assert query["error_code"] == "PROVIDER_UNSUPPORTED"


def test_query_requires_catalog_query() -> None:
    result = Query("local", "catalog")

    assert result["status"] == "fail"
    assert result["error_code"] == "INVALID_ARGUMENT"


def test_query_explicit_disconnected_provider_does_not_fallback(tmp_path: Path) -> None:
    with patch("src.extensions.ExtensionManager") as manager_type:
        manager_type.return_value.get.return_value.status = ExtensionStatus.NOT_CONFIGURED
        result = Query("spotify", "account")

    assert result["status"] == "fail"
    assert result["error_code"] == "CONNECTION_REQUIRED"
    assert result["data"]["provider"] == "spotify"


def test_query_separates_up_next_from_recent_playback() -> None:
    queued = {
        "name": "Queued",
        "artist": "Artist",
        "provider": "spotify",
        "uri": "spotify:track:queued",
        "ref": "spotify:uri:spotify:track:queued",
        "playable": True,
    }
    with patch("src.tools.agent_surface.up_next_snapshot", return_value={
        "revision": 2,
        "items": [queued],
        "failed": [],
    }), patch(
        "src.tools.agent_surface.playback_queue_snapshot",
        return_value=[{"name": "Recent", "artist": "Artist", "uri": "spotify:track:recent"}],
    ):
        queue_result = Query("local", "queue")
        recent_result = Query("local", "recent")

    assert queue_result["data"]["items"][0]["name"] == "Queued"
    assert queue_result["data"]["items"][0]["ref"] == queued["ref"]
    assert recent_result["data"]["items"][0]["name"] == "Recent"


def test_query_rehydrates_persisted_local_up_next_reference() -> None:
    ref = "local:track:persisted-test"
    queued = {
        "name": "Local Song",
        "artist": "Artist",
        "provider": "local",
        "audio_path": "/music/local-song.flac",
        "ref": ref,
        "playable": True,
    }
    with patch("src.tools.agent_surface.up_next_snapshot", return_value={
        "revision": 1,
        "items": [queued],
        "failed": [],
    }):
        result = Query("local", "queue")

    assert result["data"]["items"][0]["ref"] == ref
    with patch("src.tools.agent_surface.registry.invoke_system", return_value={
        "status": "success",
    }) as invoke:
        Call("playback.play", {"provider": "local", "ref": ref})

    invoke.assert_called_once_with(
        "play_local_song",
        {"query": "/music/local-song.flac", "player": "auto"},
    )


def test_recommend_reads_recent_once_and_aggregates_connected_authoritative_providers() -> None:
    spotify_track = {
        "name": "BB88",
        "artist": "方大同",
        "uri": "spotify:track:bb88",
    }
    manager = type(
        "Manager",
        (),
        {
            "get": lambda self, provider: type(
                "View", (), {"status": ExtensionStatus.ENABLED}
            )()
            if provider == "spotify"
            else type("View", (), {"status": ExtensionStatus.NOT_CONFIGURED})(),
        },
    )()

    with patch("src.extensions.ExtensionManager", return_value=manager), \
        patch("src.tools.agent_surface.playback_queue_snapshot", return_value=[{"name": "Recent"}]) as recent, \
        patch("src.tools.agent_surface._recommendation_preferences", return_value="R&B") as preferences, \
        patch("src.tools.agent_surface.spotify_recommend", return_value={
            "status": "success",
            "data": {"tracks": [spotify_track]},
        }) as spotify:
        result = Recommend("方大同", provider="spotify", limit=5)

    assert result["status"] == "success"
    assert [item["name"] for item in result["data"]["tracks"]] == ["BB88"]
    assert all(item.get("ref") for item in result["data"]["tracks"])
    assert result["data"]["failed"] == []
    recent.assert_called_once_with()
    preferences.assert_called_once_with()
    spotify.assert_called_once_with(
        query="方大同",
        limit=5,
        recent_tracks=[{"name": "Recent"}],
        preferences="R&B",
    )
    assert result["data"]["skipped"] == []


def test_recommend_returns_text_only_context_without_connected_provider() -> None:
    manager = type(
        "Manager",
        (),
        {
            "get": lambda self, provider: type(
                "View", (), {"status": ExtensionStatus.NOT_CONFIGURED}
            )(),
        },
    )()
    with patch("src.extensions.ExtensionManager", return_value=manager), \
        patch("src.tools.agent_surface.playback_queue_snapshot", return_value=[]), \
        patch("src.tools.agent_surface.spotify_recommend") as spotify:
        result = Recommend("jazz")

    assert result["status"] == "success"
    assert result["data"]["tracks"] == []
    assert result["data"]["text_only"] is True
    assert {item["provider"] for item in result["data"]["skipped"]} == {"spotify"}
    spotify.assert_not_called()


def test_guardrail_denies_sensitive_and_boundary_attempts() -> None:
    sensitive = inspect_script("cat ~/.ssh/id_rsa")
    boundary = inspect_script("sudo mount /dev/sda /mnt")

    assert not sensitive.allowed
    assert "sensitive-host-path" in sensitive.rule_ids
    assert not boundary.allowed
    assert "boundary-management" in boundary.rule_ids


def test_guardrail_allows_unknown_in_sandbox_semantics() -> None:
    decision = inspect_script("for item in *.flac; do printf '%s\\n' \"$item\"; done")

    assert decision.allowed
    assert decision.policy == "allowed"
    assert decision.script_length > 0


def test_sandbox_denies_execution_when_not_ready(tmp_path: Path) -> None:
    manager = SandboxManager(root=tmp_path / "sandbox")
    with patch.object(
        manager,
        "status",
        return_value=SandboxReport(SandboxState.UNAVAILABLE, "unavailable"),
    ):
        result = manager.execute("printf hello")

    assert result.policy == "sandbox_unavailable"
    assert result.exit_code is None
    assert result.audit_id


def test_sandbox_shares_network_namespace_for_provider_cli(tmp_path: Path) -> None:
    manager = SandboxManager(root=tmp_path / "sandbox")

    command = manager._base_command()

    assert "--unshare-all" in command
    assert "--share-net" in command


def test_sandbox_pipe_reader_caps_retained_output() -> None:
    buffer = bytearray()
    state = {"truncated": False}

    SandboxManager._drain_pipe(BytesIO(b"x" * (70 * 1024)), buffer, state)

    assert len(buffer) == 64 * 1024
    assert state["truncated"] is True
    assert SandboxManager._decode_output(bytes(buffer), True).endswith(
        "[output truncated]"
    )


def test_sandbox_rejects_out_of_scope_cwd_before_launch(tmp_path: Path) -> None:
    manager = SandboxManager(root=tmp_path / "sandbox")
    result = manager.execute("printf hello", cwd="/home/user")

    assert result.policy == "denied"
    assert "within /work, /music, or /tmp" in result.stderr


def test_interrupted_interaction_marker_is_one_shot_and_non_secret(tmp_path: Path) -> None:
    path = tmp_path / "interrupted.json"

    mark_interrupted_interaction(path=path)
    assert has_interrupted_interaction(path=path)
    assert "query" not in path.read_text(encoding="utf-8")
    assert (path.stat().st_mode & 0o777) == 0o600

    clear_interrupted_interaction(path=path)
    assert not has_interrupted_interaction(path=path)
