# Sonex

[简体中文](README.zh-CN.md)

Sonex is a CLI music player with a local React + Ink terminal UI and a
FastAPI/WebSocket backend. The normal user experience is one command:
`sonex` starts the backend, opens the TUI, and keeps chat, setup prompts,
confirmations, and playback state synced over WebSocket.

## Requirements

Install these system runtimes before running the Sonex installer:

- Python 3.12, available as `python3.12`
- Node.js and `npm`
- A Linux or WSL shell
- Optional: `vlc` or `mpv` for local-file and YouTube playback

The installer checks for Python, Node.js, and npm, but it does not install
system packages for you.

## Install

From the project checkout:

```bash
./scripts/install.sh
```

The installer:

- creates or reuses `.venv`
- installs the Python package and dependencies
- installs the React + Ink TUI dependencies with `npm ci`
- builds `src/cli-ui/dist/index.js`
- creates a user-facing `sonex` launcher at `~/.local/bin/sonex`

If `~/.local/bin` is not on your `PATH`, add it to your shell profile and open a
new shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Installer options:

```bash
./scripts/install.sh --no-user-shim
./scripts/install.sh --force-user-shim
./scripts/install.sh --no-launch
```

Use `--no-user-shim` to skip creating `~/.local/bin/sonex`. Use
`--force-user-shim` to replace an existing `sonex` shim for this checkout.
`--no-launch` is used by the bootstrap launcher when it repairs missing runtime
pieces.

## Start Sonex

Run the app with:

```bash
sonex
```

This starts the FastAPI backend and the React + Ink TUI together. It is the
recommended launch path.

For debugging, you can split the backend and TUI into two terminals:

```bash
sonex api
sonex tui
```

If you run `sonex tui` without the backend, the TUI will tell you that the Sonex
API is not running. In normal use, prefer `sonex`.

You can also run the internal virtualenv command directly:

```bash
.venv/bin/sonex
```

## MCP For External Agents

Sonex exposes a local MCP server so Claude Code, Codex, Hermes Agent, and other
MCP clients can use Sonex music tools. By default, MCP exposes read-only tools
such as search, account status, current playback, recent tracks, and
recommendations. Playback-changing tools are hidden unless you explicitly allow
them.

When Sonex is running normally, the FastAPI backend also serves MCP at:

```text
http://127.0.0.1:9001/mcp
```

Connect Codex:

```bash
codex mcp add sonex --url http://127.0.0.1:9001/mcp
```

Connect Claude Code over HTTP:

```bash
claude mcp add --transport http sonex http://127.0.0.1:9001/mcp
```

Connect Claude Code by spawning Sonex as a local stdio MCP server:

```bash
claude mcp add --transport stdio sonex -- sonex mcp
```

Hermes Agent can use either HTTP:

```yaml
mcp_servers:
  sonex:
    url: "http://127.0.0.1:9001/mcp"
```

or stdio:

```yaml
mcp_servers:
  sonex:
    command: "sonex"
    args: ["mcp"]
```

For debugging a standalone HTTP MCP server, run:

```bash
sonex mcp --transport http --host 127.0.0.1 --port 9002
```

The standalone debug URL is `http://127.0.0.1:9002/mcp`.

To expose playback-changing tools to trusted local agents, add
`--allow-mutations` to `sonex mcp` or set `SONEX_MCP_ALLOW_MUTATIONS=1` before
starting `sonex api`.

## Check Your Setup

Run:

```bash
./scripts/doctor.sh
```

`doctor.sh` checks Python dependencies, Node dependencies, TUI build output, the
`sonex` command, `~/.sonex`, optional local players, and Spotify configuration
status.

## Provider Setup

Sonex stores local credentials under `~/.sonex` by default. Set `SONEX_HOME` if
you want to use a different state directory.

Manage LLM provider credentials with:

```bash
sonex auth login openai
sonex auth set-key openai
sonex auth list
sonex auth set-default openai
sonex auth logout openai
```

If you start chatting before the default provider is configured, the TUI starts
an interactive setup flow before planner or agent work begins. `ollama` can be
used as a local provider when configured as the default provider.

## Music Setup

### Spotify

In the TUI, type:

```text
setup spotify
```

Sonex will guide you through creating a Spotify app, adding the loopback
redirect URI, entering the Client ID and Client Secret, and completing browser
authorization.

You can also start the Spotify OAuth flow from the CLI:

```bash
sonex auth login spotify
```

Spotify app credentials can come from `SPOTIFY_CLIENT_ID` and
`SPOTIFY_CLIENT_SECRET`, or from the guided TUI setup. Spotify playback control
requires a Spotify account and an available Spotify Connect device; Premium is
required for playback control.

### Apple Music

Apple Music setup uses developer credentials plus a Music User Token:

```bash
sonex auth set-key apple_music --api-key '<json-or-path>'
sonex auth login apple_music --access-token <music-user-token>
```

Apple Music playback requires Sonex's local MusicKit bridge.

### Local And YouTube Playback

Install `vlc` or `mpv` if you want local-file or YouTube playback. Spotify
Connect playback does not use these local players.

## Troubleshooting

- `sonex: command not found`: make sure `~/.local/bin` is on `PATH`, then run
  `./scripts/doctor.sh`.
- A different `sonex` command is found: run
  `./scripts/install.sh --force-user-shim` for this checkout.
- Runtime files are missing: run `sonex` again; the bootstrap launcher can
  repair `.venv`, TUI dependencies, and the built TUI. You can also rerun
  `./scripts/install.sh`.
- The TUI says the API is not running: launch with `sonex`, or run `sonex api`
  before `sonex tui` when debugging.
- Spotify cannot play: run `sonex auth login spotify` again, check scopes and
  account product, and make sure Spotify is open on a device.
