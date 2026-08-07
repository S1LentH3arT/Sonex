"""Main support for sonex application behavior.

Implements the main module responsibilities used by Sonex runtime flows.
Key public entry points include login, set_key, list_auth, logout, set_default_auth.
"""

from __future__ import annotations

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
from rich.table import Table

from src.auth.oauth import save_oauth_token
from src.auth.providers import get_provider_capability, normalize_provider
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
from src.log import configure_file_logging, sonex_log_path
from src.workspace import user_workspace_root

APP_VERSION = "1.0.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9001
SERVER_START_TIMEOUT = 15.0

app = typer.Typer(no_args_is_help=False, add_completion=False)
auth_app = typer.Typer(no_args_is_help=True, help="Manage Sonex provider credentials.")
console = Console()
_RETIRED_PROVIDERS = {"apple_music", "apple_mode"}


def _project_root() -> Path:
    """Prepares project root for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs project root without duplicating the local rules.

    Example: _project_root() -> returns the value used by the surrounding Sonex flow.
    """
    return Path(__file__).resolve().parents[1]


def _cli_ui_dir() -> Path:
    """Prepares cli ui dir for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs cli ui dir without duplicating the local rules.

    Example: _cli_ui_dir() -> returns the value used by the surrounding Sonex flow.
    """
    return _project_root() / "src" / "cli-ui"


def _node_bin() -> str:
    """Prepares node bin for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs node bin without duplicating the local rules.

    Example: _node_bin() -> returns the value used by the surrounding Sonex flow.
    """
    return os.getenv("SONEX_NODE", "node")


def _process_env() -> dict[str, str]:
    """Prepares process env for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs process env without duplicating the local rules.

    Example: _process_env() -> returns the value used by the surrounding Sonex flow.
    """
    env = os.environ.copy()
    project_root = str(_project_root())
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{pythonpath}" if pythonpath else project_root
    return env


def _normalize_auth_method(method: str) -> str:
    """Prepares normalize auth method for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs normalize auth method without duplicating the local rules.

    Example: _normalize_auth_method(method=...) -> returns the value used by the surrounding Sonex flow.
    """
    normalized = method.strip().lower().replace("_", "-")
    if normalized not in {"auto", "oauth", "api-key"}:
        raise typer.BadParameter("method must be one of: auto, oauth, api-key")
    return normalized


def _reject_retired_provider(provider: str) -> None:
    if provider in _RETIRED_PROVIDERS:
        console.print(f"[red]Unknown provider: {provider}.[/red]")
        raise typer.Exit(1)


def _prompt_api_key(provider: str, api_key: str | None) -> str:
    """Prepares prompt api key for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs prompt api key without duplicating the local rules.

    Example: _prompt_api_key(provider=..., api_key=...) -> returns the value used by the surrounding Sonex flow.
    """
    if api_key:
        return api_key
    value = typer.prompt(f"{provider} API key", hide_input=True)
    if not value.strip():
        raise typer.BadParameter("API key cannot be empty.")
    return value.strip()


def _print_auth_store_path(path: Path) -> None:
    """Prepares print auth store path for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs print auth store path without duplicating the local rules.

    Example: _print_auth_store_path(path=...) -> returns the value used by the surrounding Sonex flow.
    """
    console.print(f"[dim]Saved credentials to {path}[/dim]")


def _spotify_loopback_login() -> None:
    """Prepares spotify loopback login for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs spotify loopback login without duplicating the local rules.

    Example: _spotify_loopback_login() -> returns the value used by the surrounding Sonex flow.
    """
    redirect = urlparse(spotify_redirect_uri())
    host = redirect.hostname or DEFAULT_HOST
    port = redirect.port or 80
    callback_path = redirect.path or "/callback"
    received: dict[str, str] = {}

    class SpotifyCallbackHandler(BaseHTTPRequestHandler):
        """Represents spotify callback handler.

        Encapsulates spotify callback handler data and behavior used by Sonex runtime flows. Extends base h t t p request handler semantics.
        """
        def do_GET(self) -> None:
            """Coordinates do GET for the current Sonex flow.

            Typical use: Use this function when runtime code needs do GET as part of a Sonex command, playback, auth, llm, or ui path.

            Example: do_GET() -> returns the value used by the surrounding Sonex flow.
            """
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
            """Coordinates log message for the current Sonex flow.

            Typical use: Use this function when runtime code needs log message as part of a Sonex command, playback, auth, llm, or ui path.

            Example: log_message(format=...) -> returns the value used by the surrounding Sonex flow.
            """
            return

    authorize_url, expected_state = spotify_authorize_url()
    console.print("[dim]Opening Spotify authorization in your browser...[/dim]")
    console.print(f"[dim]{authorize_url}[/dim]")
    webbrowser.open(authorize_url)

    with HTTPServer((host, port), SpotifyCallbackHandler) as server:
        server.timeout = 180
        server.handle_request()

    if received.get("error"):
        console.print(f"[red]Spotify authorization failed: {received['error']}[/red]")
        raise typer.Exit(1)
    if not received.get("code"):
        console.print("[red]Spotify authorization timed out or returned no code.[/red]")
        raise typer.Exit(1)
    if received.get("state") != expected_state:
        console.print("[red]Spotify authorization state mismatch.[/red]")
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
    api_key: str | None = typer.Option(None, "--api-key", help="Provider API key."),
    access_token: str | None = typer.Option(None, "--access-token", help="OAuth access token."),
    refresh_token: str | None = typer.Option(None, "--refresh-token", help="OAuth refresh token."),
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

    if name == "spotify" and selected_method in {"auto", "oauth"} and not access_token:
        _spotify_loopback_login()
        return

    if selected_method == "oauth" or (
        selected_method == "auto" and capability.supports_oauth and access_token
    ):
        if not capability.supports_oauth:
            console.print(
                f"[red]Provider '{name}' does not support OAuth in Sonex yet. Use API key login instead.[/red]"
            )
            raise typer.Exit(1)
        if not access_token:
            console.print(
                f"[yellow]OAuth for '{name}' is token-import based in this version. "
                "Pass --access-token, or use --method api-key.[/yellow]"
            )
            raise typer.Exit(1)
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

    if selected_method == "oauth":
        console.print(
            f"[red]Provider '{name}' does not support OAuth in Sonex yet. Use API key login instead.[/red]"
        )
        raise typer.Exit(1)

    if not capability.requires_auth:
        path = set_provider_config(name, model=model, base_url=base_url)
        _print_auth_store_path(path)
        return

    if not capability.supports_api_key:
        console.print(f"[red]Provider '{name}' does not support API key login.[/red]")
        raise typer.Exit(1)

    key = _prompt_api_key(name, api_key)
    path = set_api_key(name, key, model=model, base_url=base_url)
    _print_auth_store_path(path)


@auth_app.command("set-key")
def set_key(
    provider: str,
    api_key: str | None = typer.Option(None, "--api-key", help="Provider API key."),
    model: str | None = typer.Option(None, "--model", help="Default model for this provider."),
    base_url: str | None = typer.Option(None, "--base-url", help="Provider base URL."),
) -> None:
    """Store or update a provider API key."""
    name = normalize_provider(provider)
    _reject_retired_provider(name)
    capability = get_provider_capability(name)
    if not capability.supports_api_key:
        console.print(f"[red]Provider '{name}' does not support API key login.[/red]")
        raise typer.Exit(1)
    key = _prompt_api_key(name, api_key)
    path = set_api_key(name, key, model=model, base_url=base_url)
    _print_auth_store_path(path)


@auth_app.command("list")
def list_auth() -> None:
    """List configured providers without exposing secrets."""
    store = load_auth_store()
    console.print(f"[dim]Auth store: {auth_store_path()}[/dim]")
    if store.default_provider:
        console.print(f"[dim]Default provider: {store.default_provider}[/dim]")
    if store.default_model:
        console.print(f"[dim]Default model: {store.default_model}[/dim]")
    table = Table("Provider", "Method", "API key", "OAuth", "Model", "Base URL", "Updated")
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
        console.print(f"[green]Removed credentials for {name}.[/green]")
    else:
        console.print(f"[yellow]No credentials found for {name}.[/yellow]")


@auth_app.command("set-default")
def set_default_auth(
    provider: str,
    model: str | None = typer.Option(None, "--model", help="Default model."),
) -> None:
    """Set the default LLM provider and optional default model."""
    _reject_retired_provider(normalize_provider(provider))
    path = set_default(provider, model=model)
    _print_auth_store_path(path)


def _dist_entry() -> Path:
    """Prepares dist entry for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs dist entry without duplicating the local rules.

    Example: _dist_entry() -> returns the value used by the surrounding Sonex flow.
    """
    return _cli_ui_dir() / "dist" / "index.js"


def _tsc_entry() -> Path:
    """Prepares tsc entry for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs tsc entry without duplicating the local rules.

    Example: _tsc_entry() -> returns the value used by the surrounding Sonex flow.
    """
    return _cli_ui_dir() / "node_modules" / "typescript" / "bin" / "tsc"


def _build_ink_ui_if_needed() -> None:
    """Prepares build ink ui if needed for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs build ink ui if needed without duplicating the local rules.

    Example: _build_ink_ui_if_needed() -> returns the value used by the surrounding Sonex flow.
    """
    if _dist_entry().exists():
        return

    tsc = _tsc_entry()
    if not tsc.exists():
        raise typer.BadParameter(
            "Ink UI dependencies are missing. Install dependencies in src/cli-ui first."
        )

    console.print("[dim]Building React + Ink TUI...[/dim]")
    subprocess.run(
        [_node_bin(), str(tsc), "--outDir", "dist"],
        cwd=_cli_ui_dir(),
        env=_process_env(),
        check=True,
    )


def _run_ink_tui(host: str, port: int) -> int:
    """Prepares run ink tui for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs run ink tui without duplicating the local rules.

    Example: _run_ink_tui(host=..., port=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares wait for server for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs wait for server without duplicating the local rules.

    Example: _wait_for_server(host=..., port=..., timeout=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares start api process for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs start api process without duplicating the local rules.

    Example: _start_api_process(host=..., port=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    """Prepares run full tui for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs run full tui without duplicating the local rules.

    Example: _run_full_tui(host=..., port=...) -> returns the value used by the surrounding Sonex flow.
    """
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
) -> None:
    """Coordinates main for the current Sonex flow.

    Typical use: Use this function when runtime code needs main as part of a Sonex command, playback, auth, llm, or ui path.

    Example: main(ctx=..., version=..., host=..., port=...) -> returns the value used by the surrounding Sonex flow.
    """
    if version:
        typer.echo(f"v{APP_VERSION}")
        raise typer.Exit()

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


if __name__ == "__main__":
    app()
