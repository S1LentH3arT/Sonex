"""Main support for sonex application behavior.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import typer
import uvicorn
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from typer.exceptions import Abort, TyperException
from typer.main import get_command

from src.auth.oauth import save_oauth_token
from src.auth.providers import get_provider_capability, normalize_provider, provider_names
from src.auth.spotify import (
    save_spotify_token_info,
    spotify_authorize_url,
    spotify_oauth_manager,
    spotify_redirect_uri,
)
from src.auth.store import (
    auth_store_path,
    load_auth_store,
    provider_to_public_dict,
    remove_provider,
    set_api_key,
    set_default,
    set_provider_config,
)
from src.extensions import ExtensionManager
from src.llm.models import list_provider_models
from src.log import configure_file_logging, sonex_home, sonex_log_path
from src.memory.tool import search_memory
from src.network.proxy import (
    DIRECT,
    PROXY,
    ProxyConfigError,
    configure_startup_proxy,
    proxy_status,
    save_and_apply,
)
from src.sandbox import SandboxManager, SandboxState
from src.thinking.config import ThinkingConfig
from src.tools.agent_catalog import QUERY_PROVIDERS
from src.tools.agent_surface import Query
from src.tools.playlists import list_playlists, playlist_snapshot
from src.tools.audio_doctor import audio_doctor_report
from src.tools.youtube_runtime import (
    refresh_local_health_check,
    runtime_status,
    start_background_health_check,
    update_state,
)
from src.workspace import user_workspace_root

DEFAULT_APP_VERSION = "0.1.0-alpha.4"
APP_VERSION = os.getenv("SONEX_APP_VERSION", DEFAULT_APP_VERSION)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9001
SERVER_START_TIMEOUT = 15.0

class _CliTyper(typer.Typer):
    """Keep Click's exit semantics while giving shell errors a light style."""

    def __call__(self, *args: object, **kwargs: object) -> object:
        kwargs["standalone_mode"] = False
        try:
            result = get_command(self)(*args, **kwargs)
        except TyperException as exc:
            _show_cli_error(exc)
            raise SystemExit(exc.exit_code) from exc
        except Abort:
            _error_console.print("[red]Aborted![/red]")
            raise SystemExit(1) from None
        if isinstance(result, int) and result:
            raise SystemExit(result)
        return result


app = _CliTyper(no_args_is_help=False, add_completion=True, rich_markup_mode=None)
auth_app = typer.Typer(no_args_is_help=True, help="Manage Sonex provider credentials.", rich_markup_mode=None)
doctor_app = typer.Typer(no_args_is_help=True, help="Inspect local Sonex runtime health.", rich_markup_mode=None)
youtube_app = typer.Typer(no_args_is_help=True, help="Inspect the built-in YouTube extension.", rich_markup_mode=None)
extension_app = typer.Typer(no_args_is_help=True, help="Inspect built-in music extensions.", rich_markup_mode=None)
sandbox_app = typer.Typer(no_args_is_help=True, help="Inspect the Agent sandbox.", rich_markup_mode=None)
model_app = typer.Typer(no_args_is_help=True, help="Inspect configured LLM models.", rich_markup_mode=None)
memory_app = typer.Typer(no_args_is_help=True, help="Search Sonex memory.", rich_markup_mode=None)
playlist_app = typer.Typer(no_args_is_help=True, help="Inspect local playlists.", rich_markup_mode=None)
proxy_app = typer.Typer(no_args_is_help=True, help="Configure Sonex outbound proxy routing.", rich_markup_mode=None)
app.add_typer(auth_app, name="auth")
app.add_typer(doctor_app, name="doctor")
app.add_typer(youtube_app, name="youtube")
app.add_typer(extension_app, name="extension")
app.add_typer(sandbox_app, name="sandbox")
app.add_typer(model_app, name="model")
app.add_typer(memory_app, name="memory")
app.add_typer(playlist_app, name="playlist")
app.add_typer(proxy_app, name="proxy")
console = Console(style="bright_white")
_error_console = Console(stderr=True, style="bright_white")
_RETIRED_PROVIDERS = {"apple_music", "apple_mode"}

_ERROR_EXIT_CODES = {
    "CONNECTION_REQUIRED": 3,
    "AUTH_REQUIRED": 3,
    "CONFIG_REQUIRED": 3,
    "SPOTIFY_LOGIN_REQUIRED": 3,
    "RESOURCE_UNSUPPORTED": 4,
    "PROVIDER_UNSUPPORTED": 4,
}


def _show_cli_error(exc: TyperException) -> None:
    ctx = getattr(exc, "ctx", None)
    if ctx is not None:
        typer.echo(ctx.get_usage(), err=True)
        help_option = ctx.command.get_help_option(ctx)
        if help_option is not None:
            typer.echo(f"Try '{ctx.command_path} {help_option.opts[-1]}' for help.", err=True)
    _error_console.print(f"[red]Error: {escape(exc.format_message())}[/red]")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cli_ui_dir() -> Path:
    configured = os.getenv("SONEX_CLI_UI_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / "src" / "cli-ui"


def _node_bin() -> str:
    return os.getenv("SONEX_NODE", "node")


def _process_env() -> dict[str, str]:
    env = os.environ.copy()
    project_root = str(_project_root())
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{pythonpath}" if pythonpath else project_root
    return env


def _normalize_auth_method(method: str) -> str:
    normalized = method.strip().lower().replace("_", "-")
    if normalized not in {"auto", "oauth", "api-key"}:
        raise typer.BadParameter("method must be one of: auto, oauth, api-key")
    return normalized


def _reject_retired_provider(provider: str) -> None:
    if provider in _RETIRED_PROVIDERS:
        _error_console.print(f"[red]Unknown provider: {provider}.[/red]")
        raise typer.Exit(1)


@proxy_app.command("set")
def proxy_set(url: str) -> None:
    """Save and enable an HTTP or SOCKS5 proxy."""
    try:
        config = save_and_apply(PROXY, url)
    except (ProxyConfigError, OSError) as exc:
        raise typer.BadParameter(str(exc), param_hint="url") from exc
    typer.echo(f"Proxy enabled: {config.url}")


@proxy_app.command("disable")
def proxy_disable() -> None:
    """Save Direct mode while retaining the configured proxy address."""
    try:
        save_and_apply(DIRECT)
    except (ProxyConfigError, OSError) as exc:
        raise typer.Exit(f"Unable to save proxy configuration: {exc}") from exc
    typer.echo("Direct mode enabled. Requests will not use a proxy.")


@proxy_app.command("status")
def proxy_status_command(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show the active proxy route and override source."""
    payload = proxy_status()
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False))
        return
    typer.echo(f"mode: {payload['mode']}")
    typer.echo(f"url: {payload['url'] or '-'}")
    typer.echo(f"source: {payload['source']}")
    if payload["environment_override"]:
        typer.echo(f"environment: {payload['environment_url']}")


def _provider_secret_env_names(provider: str, kind: str) -> tuple[str, ...]:
    stem = normalize_provider(provider).upper()
    names = [f"SONEX_{stem}_{kind}"]
    if kind == "API_KEY" and provider == "openai":
        names.append("SONEX_API_KEY")
    if kind == "API_KEY" and provider == "kimi_global":
        names.append("SONEX_KIMI_API_KEY")
    if kind == "API_KEY" and provider == "minimax_global":
        names.append("SONEX_MINIMAX_API_KEY")
    return tuple(names)


def _read_secret(provider: str, kind: str, *, optional: bool = False) -> str | None:
    env_names = _provider_secret_env_names(provider, kind)
    for name in env_names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    if optional:
        return None
    if sys.stdin.isatty():
        value = typer.prompt(f"{provider} {kind.replace('_', ' ').lower()}", hide_input=True).strip()
    else:
        value = sys.stdin.read().strip()
    if not value and not optional:
        raise typer.BadParameter(
            f"Missing {kind.lower().replace('_', ' ')}. Set {env_names[0]} or provide it via stdin."
        )
    return value or None


def _prompt_api_key(provider: str) -> str:
    value = _read_secret(provider, "API_KEY")
    assert value is not None
    return value


def _print_auth_store_path(path: Path) -> None:
    console.print(f"[bright_white]Saved credentials to {path}[/bright_white]")


def _spotify_loopback_login() -> None:
    redirect = urlparse(spotify_redirect_uri())
    host = redirect.hostname or DEFAULT_HOST
    port = redirect.port or 80
    callback_path = redirect.path or "/callback"
    received: dict[str, str] = {}

    class SpotifyCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            if params.get("error"):
                received["error"] = params["error"][0]
            if params.get("code"):
                received["code"] = params["code"][0]
            if params.get("state"):
                received["state"] = params["state"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Spotify connected. You can return to Sonex.")

        def log_message(self, format: str, *args: object) -> None:
            return

    authorize_url, expected_state = spotify_authorize_url()
    console.print("[bright_white]Opening Spotify authorization in your browser...[/bright_white]")
    console.print(f"[bright_white]{authorize_url}[/bright_white]")
    webbrowser.open(authorize_url)

    with HTTPServer((host, port), SpotifyCallbackHandler) as server:
        server.timeout = 180
        server.handle_request()

    if received.get("error"):
        _error_console.print(f"[red]Spotify authorization failed: {received['error']}[/red]")
        raise typer.Exit(1)
    if not received.get("code"):
        _error_console.print("[red]Spotify authorization timed out or returned no code.[/red]")
        raise typer.Exit(1)
    if received.get("state") != expected_state:
        _error_console.print("[red]Spotify authorization state mismatch.[/red]")
        raise typer.Exit(1)

    token_info = spotify_oauth_manager(state=expected_state).get_access_token(
        received["code"],
        as_dict=True,
        check_cache=False,
    )
    save_spotify_token_info(token_info)
    _print_auth_store_path(auth_store_path())


@auth_app.command()
def login(
    provider: str,
    method: str = typer.Option("auto", "--method", help="auto, oauth, or api-key."),
    expires_at: str | None = typer.Option(None, "--expires-at", help="OAuth token expiry ISO timestamp."),
    scope: list[str] | None = typer.Option(None, "--scope", help="OAuth scope. Repeat for multiple scopes."),
    model: str | None = typer.Option(None, "--model", help="Default model for this provider."),
    base_url: str | None = typer.Option(None, "--base-url", help="Provider base URL."),
) -> None:
    """Login to a provider or import provider credentials."""
    name = normalize_provider(provider)
    _reject_retired_provider(name)
    selected_method = _normalize_auth_method(method)
    capability = get_provider_capability(name)

    if name == "spotify" and selected_method in {"auto", "oauth"}:
        _spotify_loopback_login()
        return

    if selected_method == "oauth":
        if not capability.supports_oauth:
            _error_console.print(
                f"[red]Provider '{name}' does not support OAuth in Sonex yet. Use API key login instead.[/red]"
            )
            raise typer.Exit(1)
        access_token = _read_secret(name, "ACCESS_TOKEN")
        refresh_token = _read_secret(name, "REFRESH_TOKEN", optional=True)
        save_oauth_token(
            name,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=scope or [],
            model=model,
            base_url=base_url,
        )
        _print_auth_store_path(auth_store_path())
        return

    if not capability.requires_auth:
        path = set_provider_config(name, model=model, base_url=base_url)
        _print_auth_store_path(path)
        return

    if not capability.supports_api_key:
        _error_console.print(f"[red]Provider '{name}' does not support API key login.[/red]")
        raise typer.Exit(1)

    key = _prompt_api_key(name)
    path = set_api_key(name, key, model=model, base_url=base_url)
    _print_auth_store_path(path)


@auth_app.command("list")
def list_auth(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List configured providers without exposing secrets."""
    store = load_auth_store()
    providers = [
        provider_to_public_dict(provider)
        for provider in sorted(store.providers.values(), key=lambda item: item.name)
    ]
    payload = {
        "auth_store": str(auth_store_path()),
        "default_provider": store.default_provider,
        "default_model": store.default_model,
        "providers": providers,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    console.print(f"[bright_white]Auth store: {auth_store_path()}[/bright_white]")
    if store.default_provider:
        console.print(f"[bright_white]Default provider: {store.default_provider}[/bright_white]")
    if store.default_model:
        console.print(f"[bright_white]Default model: {store.default_model}[/bright_white]")
    table = Table(
        box=None,
        header_style="bold bright_white",
        pad_edge=False,
        padding=(0, 1),
    )
    for heading in ("Provider", "Method", "API key", "OAuth", "Model", "Base URL", "Updated"):
        table.add_column(heading, overflow="fold")
    for provider in sorted(store.providers.values(), key=lambda item: item.name):
        public = provider_to_public_dict(provider)
        table.add_row(
            public["provider"],
            public["auth_method"],
            public["api_key"],
            public["oauth"],
            public["model"],
            public["base_url"],
            public["updated_at"],
        )
    console.print(table)


@auth_app.command()
def logout(provider: str) -> None:
    """Remove stored credentials for a provider."""
    name = normalize_provider(provider)
    _reject_retired_provider(name)
    removed = remove_provider(name)
    if removed:
        console.print(f"[bright_white]Removed credentials for {name}.[/bright_white]")
    else:
        _error_console.print(f"[yellow]No credentials found for {name}.[/yellow]")


@auth_app.command("set-default")
def set_default_auth(
    provider: str,
    model: str | None = typer.Option(None, "--model", help="Default model."),
) -> None:
    """Set the default LLM provider and optional default model."""
    name = normalize_provider(provider)
    _reject_retired_provider(name)
    path = set_default(name, model=model)
    _print_auth_store_path(path)


def _emit_result(result: dict[str, object], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, default=str))
    elif str(result.get("status") or "").casefold() not in {"success", "ok"}:
        typer.echo(str(result.get("message") or "Command failed."), err=True)
    else:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    typer.echo(str(item))
                    continue
                title = str(item.get("title") or item.get("name") or item.get("id") or "-")
                artist = str(item.get("artist") or "").strip()
                provider = str(item.get("provider") or "").strip()
                suffix = " · ".join(part for part in (artist, provider) if part)
                typer.echo(f"{title}{f' ({suffix})' if suffix else ''}")
            if not items:
                typer.echo(str(result.get("message") or "No results."))
        else:
            typer.echo(str(result.get("message") or json.dumps(data, ensure_ascii=False, default=str)))
    if str(result.get("status") or "").casefold() not in {"success", "ok"}:
        error_code = str(result.get("error_code") or "")
        raise typer.Exit(_ERROR_EXIT_CODES.get(error_code, 1))


def _local_thinking_defaults() -> tuple[str, str]:
    config_path = Path(os.getenv("SONEX_CONFIG_PATH") or (sonex_home() / "thinking.json")).expanduser()
    file_config: dict[str, object] = {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            file_config = loaded
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    providers = file_config.get("providers") if isinstance(file_config.get("providers"), dict) else {}
    store = load_auth_store()
    default_provider = normalize_provider(
        str(
            os.getenv("SONEX_DEFAULT_PROVIDER")
            or os.getenv("SONEX_PROVIDER")
            or store.default_provider
            or file_config.get("default_provider")
            or "openai"
        )
    )
    provider_config = providers.get(default_provider) if isinstance(providers, dict) else {}
    provider_auth = store.providers.get(default_provider)
    provider_config = provider_config if isinstance(provider_config, dict) else {}
    default_model = str(
        os.getenv("SONEX_DEFAULT_MODEL")
        or os.getenv("SONEX_MODEL")
        or store.default_model
        or file_config.get("default_model")
        or os.getenv(f"SONEX_{default_provider.upper()}_MODEL")
        or (provider_auth.model if provider_auth else None)
        or provider_config.get("model")
        or get_provider_capability(default_provider).default_model
        or "gpt-5.5"
    )
    return default_provider, default_model


@app.command("status")
def status(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show local Sonex runtime, configuration, extension, and sandbox state."""
    default_provider, default_model = _local_thinking_defaults()
    runtime_dir = Path(os.getenv("SONEX_RUNTIME_DIR", "")) if os.getenv("SONEX_RUNTIME_DIR") else None
    runtime_marker = runtime_dir / "runtime.json" if runtime_dir else None
    managed_runtime = bool(runtime_marker and runtime_marker.is_file())
    extensions = [view.to_dict() for view in ExtensionManager().snapshot()]
    sandbox = SandboxManager().status()
    payload = {
        "version": APP_VERSION,
        "runtime": {
            "python": sys.executable,
            "python_version": ".".join(str(part) for part in sys.version_info[:3]),
            "managed": managed_runtime,
            "ready": sys.version_info >= (3, 12),
        },
        "config": {"default_provider": default_provider, "default_model": default_model},
        "extensions": extensions,
        "sandbox": {
            "state": sandbox.state.value,
            "message": sandbox.message,
            "missing": list(sandbox.missing),
            "work_dir": sandbox.work_dir,
        },
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    typer.echo(f"version: {payload['version']}")
    typer.echo(f"python: {payload['runtime']['python']} ({payload['runtime']['python_version']})")
    typer.echo(f"managed runtime: {'ready' if managed_runtime else 'no'}")
    typer.echo(f"default: {default_provider} / {default_model}")
    extension_summary = ", ".join(f"{item['id']}={item['status']}" for item in extensions)
    typer.echo(f"extensions: {extension_summary}")
    typer.echo(f"sandbox: {sandbox.state.value}")


@extension_app.command("list")
def extension_list(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List built-in music extensions without changing their state."""
    views = [view.to_dict() for view in ExtensionManager().snapshot()]
    if json_output:
        typer.echo(json.dumps({"extensions": views}, ensure_ascii=False, default=str))
        return
    for view in views:
        typer.echo(f"{view['id']}: {view['status']} - {view['description']}")


@extension_app.command("status")
def extension_status(
    name: str,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show one built-in music extension without changing its state."""
    try:
        view = ExtensionManager().get(normalize_provider(name)).to_dict()
    except Exception as exc:
        raise typer.BadParameter(str(exc), param_hint="name") from exc
    if json_output:
        typer.echo(json.dumps(view, ensure_ascii=False, default=str))
    else:
        typer.echo(f"{view['id']}: {view['status']}")
        if view.get("reason_code"):
            typer.echo(f"reason: {view['reason_code']}")


@sandbox_app.command("status")
def sandbox_status(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show local Agent sandbox readiness without configuring it."""
    report = SandboxManager().status()
    payload = {
        "state": report.state.value,
        "message": report.message,
        "missing": list(report.missing),
        "work_dir": report.work_dir,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        typer.echo(f"{report.state.value}: {report.message}")
        if report.missing:
            typer.echo(f"missing: {', '.join(report.missing)}")
    if report.state is SandboxState.UNCONFIGURED:
        raise typer.Exit(3)
    if report.state is SandboxState.UNAVAILABLE:
        raise typer.Exit(4)


@model_app.command("list")
def model_list(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List models for configured LLM providers."""
    store = load_auth_store()
    runtime = ThinkingConfig.get_runtime_config()
    llm_providers = provider_names() - {"spotify"}
    configured = (set(store.providers) & llm_providers) | {runtime.default_provider}
    for provider in llm_providers:
        if os.getenv(f"SONEX_{provider.upper()}_API_KEY") or os.getenv(f"SONEX_{provider.upper()}_MODEL"):
            configured.add(provider)
    models: list[dict[str, object]] = []
    for provider in sorted(configured):
        config = runtime.get_provider(provider)
        for item in list_provider_models(config):
            models.append({
                "id": item.id,
                "label": item.label,
                "provider": item.provider,
                "description": item.description,
                "deprecated": item.deprecated,
                "source": item.source,
                "default": provider == runtime.default_provider and item.id == runtime.default_model,
            })
    payload = {"default_provider": runtime.default_provider, "default_model": runtime.default_model, "models": models}
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    for item in models:
        marker = " *" if item["default"] else ""
        typer.echo(f"{item['provider']}: {item['id']}{marker}")


@memory_app.command("search")
def memory_search(
    query: str,
    target: str = typer.Option("all", "--target", help="memory, user, or all."),
    limit: int = typer.Option(10, "--limit", min=1, max=50),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Search long-term Sonex memory without changing it."""
    try:
        entries = search_memory(query=query, target=target, limit=limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="target") from exc
    except OSError as exc:
        typer.echo(f"Memory search unavailable: {exc}", err=True)
        raise typer.Exit(1) from exc
    payload = {"query": query, "target": target, "items": entries}
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    for entry in entries:
        typer.echo(f"{entry.get('target', '-')}:{entry.get('source_path', '-')}:{entry.get('line_no', '-')} {entry.get('content', '')}")
    if not entries:
        typer.echo("No memory matches.")


@app.command("search")
def search(
    query: str,
    provider: str = typer.Option("current", "--provider", help=f"Music provider: {', '.join(QUERY_PROVIDERS)}."),
    limit: int = typer.Option(10, "--limit", min=1, max=50),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Search one music provider without invoking the Agent or playback."""
    _emit_result(Query(provider, "catalog", query=query, limit=limit), json_output=json_output)


@app.command("recent")
def recent(
    provider: str = typer.Option("current", "--provider", help=f"Music provider: {', '.join(QUERY_PROVIDERS)}."),
    limit: int = typer.Option(10, "--limit", min=1, max=50),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show recent tracks from one music provider without playback."""
    _emit_result(Query(provider, "recent", limit=limit), json_output=json_output)


@playlist_app.command("list")
def playlist_list(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List local Sonex playlists without changing them."""
    payload = {"playlists": list_playlists()}
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    for item in payload["playlists"]:
        typer.echo(f"{item['name']}: {item['track_count']} track(s)")


@playlist_app.command("show")
def playlist_show(
    name: str,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show one local Sonex playlist without changing it."""
    playlists = list_playlists()
    match = next((item for item in playlists if str(item["name"]).casefold() == name.casefold()), None)
    if match is None:
        typer.echo(f"Playlist not found: {name}", err=True)
        raise typer.Exit(3)
    payload = {"playlist": playlist_snapshot(str(match["name"]))}
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    playlist = payload["playlist"]
    typer.echo(f"{playlist.get('name', name)}: {len(playlist.get('tracks') or [])} track(s)")
    for track in playlist.get("tracks") or []:
        typer.echo(f"{track.get('title') or track.get('name') or '-'} ({track.get('artist') or '-'})")


def _dist_entry() -> Path:
    return _cli_ui_dir() / "dist" / "index.js"


def _tsc_entry() -> Path:
    return _cli_ui_dir() / "node_modules" / "typescript" / "bin" / "tsc"


def _build_ink_ui_if_needed() -> None:
    if _dist_entry().exists():
        return

    if os.getenv("SONEX_CLI_UI_DIR"):
        raise typer.BadParameter(
            "Published Sonex package is missing its prebuilt TUI. Reinstall the package."
        )

    tsc = _tsc_entry()
    if not tsc.exists():
        raise typer.BadParameter(
            "Ink UI dependencies are missing. Install dependencies in src/cli-ui first."
        )

    console.print("[bright_white]Building React + Ink TUI...[/bright_white]")
    subprocess.run(
        [_node_bin(), str(tsc), "--outDir", "dist"],
        cwd=_cli_ui_dir(),
        env=_process_env(),
        check=True,
    )


def _run_ink_tui(host: str, port: int) -> int:
    _build_ink_ui_if_needed()
    env = _process_env()
    env["SONEX_WS_URL"] = f"ws://{host}:{port}/ws"
    env["SONEX_LAUNCH_CWD"] = str(Path.cwd().resolve())

    proc = subprocess.run(
        [_node_bin(), str(_dist_entry())],
        cwd=user_workspace_root(),
        env=env,
        check=False,
    )
    return int(proc.returncode or 0)


def _wait_for_server(host: str, port: int, timeout: float = SERVER_START_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"Timed out waiting for Sonex API at {host}:{port}{detail}")


def _start_api_process(host: str, port: int) -> subprocess.Popen[bytes]:
    log_fd = os.open(sonex_log_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.api.app:app",
                "--host",
                host,
                "--port",
                str(port),
                "--log-level",
                os.getenv("SONEX_UVICORN_LOG_LEVEL", "warning"),
            ],
            cwd=user_workspace_root(),
            env=_process_env(),
            stdout=log_fd,
            stderr=subprocess.STDOUT,
        )
    finally:
        os.close(log_fd)


def _run_full_tui(host: str, port: int) -> None:
    api_proc = _start_api_process(host, port)
    try:
        _wait_for_server(host, port)
        exit_code = _run_ink_tui(host, port)
    finally:
        api_proc.terminate()
        try:
            api_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            api_proc.kill()
            api_proc.wait(timeout=5)

    if exit_code:
        raise typer.Exit(exit_code)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", is_eager=True),
    host: str = typer.Option(DEFAULT_HOST, "--host", help="WebSocket API host."),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="WebSocket API port."),
    proxy: str | None = typer.Option(None, "--proxy", help="Use an HTTP or SOCKS5 proxy."),
    no_proxy: bool = typer.Option(False, "--no-proxy", help="Use Direct mode and clear proxy routing."),
) -> None:
    if version:
        typer.echo(f"v{APP_VERSION}")
        raise typer.Exit()

    try:
        configure_startup_proxy(cli_proxy=proxy, cli_no_proxy=no_proxy)
    except (ProxyConfigError, OSError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--proxy/--no-proxy") from exc

    if ctx.invoked_subcommand in {None, "api", "tui"}:
        start_background_health_check()

    if ctx.invoked_subcommand is None:
        _run_full_tui(host=host, port=port)
        raise typer.Exit()


@app.command()
def api(
    host: str = typer.Option(DEFAULT_HOST, "--host", help="Bind host."),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="Bind port."),
) -> None:
    """Run only the Sonex WebSocket API."""
    os.chdir(user_workspace_root())
    configure_file_logging()
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        log_level=os.getenv("SONEX_UVICORN_LOG_LEVEL", "warning"),
    )


@app.command()
def tui(
    host: str = typer.Option(DEFAULT_HOST, "--host", help="WebSocket API host."),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="WebSocket API port."),
) -> None:
    """Run only the React + Ink TUI."""
    exit_code = _run_ink_tui(host=host, port=port)
    if exit_code:
        raise typer.Exit(exit_code)


@doctor_app.command("audio")
def doctor_audio(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    check_updates: bool = typer.Option(True, "--check-updates/--no-check-updates", help="Check the latest stable yt-dlp release."),
) -> None:
    """Check yt-dlp, worker isolation, local audio state, and cooldown."""
    report = audio_doctor_report(check_updates=check_updates)
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False, default=str))
        return
    typer.echo(f"yt-dlp: {report['yt_dlp_version']}")
    typer.echo(f"worker: {'ready' if report['worker_module'] else 'missing'}")
    youtube_runtime = report.get("youtube_runtime") or {}
    typer.echo(
        f"YouTube runtime: {youtube_runtime.get('status', 'unknown')} "
        f"(provider {youtube_runtime.get('provider_runtime', 'unknown')})"
    )
    typer.echo(f"audio state: {'writable' if report['storage_writable'] else 'read-only'} ({report['storage_path']})")
    cooldown = report.get("cooldown")
    if cooldown and cooldown.get("remaining_seconds", 0) > 0:
        typer.echo(
            f"YouTube cooldown: {cooldown['failure_class']} "
            f"({int(cooldown['remaining_seconds'])}s remaining)"
        )
    else:
        typer.echo("YouTube cooldown: clear")
    if report.get("latest_version"):
        update = "available" if report["update_available"] else "current"
        typer.echo(f"latest stable: {report['latest_version']} ({update})")
    elif report.get("update_error"):
        typer.echo("latest stable: unavailable")


@youtube_app.command("status")
def youtube_status(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    refresh: bool = typer.Option(False, "--refresh", help="Start a local background health refresh."),
) -> None:
    """Read the built-in YouTube runtime state without starting playback."""
    if refresh:
        refresh_local_health_check()
    report = {
        "runtime": runtime_status(),
        "update": update_state(),
    }
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False, default=str))
    else:
        runtime = report["runtime"]
        update = report["update"]
        typer.echo(f"status: {runtime.get('status')}")
        typer.echo(f"provider: {runtime.get('provider_runtime')}")
        if runtime.get("yt_dlp_version"):
            typer.echo(f"yt-dlp: {runtime['yt_dlp_version']}")
        if runtime.get("provider_version"):
            typer.echo(f"PO Token Provider: {runtime['provider_version']}")
        if runtime.get("status") == "restart_required":
            typer.echo("Restart Sonex to apply the staged YouTube runtime update.")
        if update.get("status") not in {None, "idle"}:
            typer.echo(f"updater: {update.get('status')} ({update.get('phase', 'unknown')})")
            if update.get("error"):
                typer.echo(f"updater error: {update['error']}", err=True)
    status = str(report["runtime"].get("status") or "degraded")
    if status in {"ready", "restart_required"}:
        return
    if status == "setup_required":
        raise typer.Exit(2)
    raise typer.Exit(3)


if __name__ == "__main__":
    app()
