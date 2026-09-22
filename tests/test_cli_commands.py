"""Contracts for the scriptable Sonex CLI surface."""

from __future__ import annotations

import json

from typer.testing import CliRunner

import src.main as main
from src.auth.store import load_auth_store, set_api_key


runner = CliRunner()


def test_auth_is_mounted_and_secret_flags_are_not_public() -> None:
    result = runner.invoke(main.app, ["auth", "login", "--help"])

    assert result.exit_code == 0
    assert "set-key" not in result.stdout
    assert "--api-key" not in result.stdout
    assert "--access-token" not in result.stdout


def test_auth_login_reads_api_key_from_stdin(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SONEX_HOME", str(tmp_path))

    result = runner.invoke(main.app, ["auth", "login", "openai"], input="sk-from-stdin\n")

    assert result.exit_code == 0
    assert load_auth_store(tmp_path / "auth.json").providers["openai"].api_key == "sk-from-stdin"


def test_auth_list_json_redacts_secrets(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SONEX_HOME", str(tmp_path))
    set_api_key("openai", "sk-secret", path=tmp_path / "auth.json")

    result = runner.invoke(main.app, ["auth", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["providers"][0]["api_key"] == "sk-s...cret"
    assert "sk-secret" not in result.stdout


def test_search_reports_provider_error_as_json_with_stable_exit_code() -> None:
    result = runner.invoke(main.app, ["search", "song", "--provider", "unknown", "--json"])

    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "PROVIDER_UNSUPPORTED"


def test_help_exposes_native_completion() -> None:
    result = runner.invoke(main.app, ["--help"])

    assert result.exit_code == 0
    assert "--show-completion" in result.stdout


def test_shell_help_and_errors_are_borderless() -> None:
    help_result = runner.invoke(main.app, ["auth", "--help"])
    error_result = runner.invoke(main.app, ["auth", "unknown"])

    assert help_result.exit_code == 0
    assert error_result.exit_code == 2
    assert not any(glyph in help_result.stdout for glyph in ("╭", "╰", "│", "─"))
    assert not any(glyph in error_result.output for glyph in ("╭", "╰", "│", "─"))
    assert "Error: No such command 'unknown'." in error_result.output


def test_auth_list_uses_borderless_wrapped_table(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SONEX_HOME", str(tmp_path))
    set_api_key("openai", "sk-secret", path=tmp_path / "auth.json")

    result = runner.invoke(main.app, ["auth", "list"])

    assert result.exit_code == 0
    assert "Provider  Method" in result.stdout
    assert "openai" in result.stdout
    assert not any(glyph in result.stdout for glyph in ("┏", "┓", "┗", "┛", "┃", "╋"))
