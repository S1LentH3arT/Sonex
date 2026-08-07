<div align="center">
  <h1>Sonex</h1>
  <p><strong>An AI-powered music agent for the terminal.</strong></p>
  <p>
    <a href="README.md">English</a> ·
    <a href="README.zh-CN.md">简体中文</a>
  </p>
</div>

---

Sonex is a CLI music player with a local React + Ink terminal UI and a
FastAPI/WebSocket backend. The normal user experience is one command:
`sonex` starts the backend, opens the TUI, and keeps chat, setup prompts,
confirmations, and playback state synced over WebSocket.

## Requirements

Install these system runtimes before running the Sonex installer:

| Requirement | Notes |
| --- | --- |
| Python 3.12 | Must be available as `python3.12` |
| Node.js and `npm` | Required to install and build the terminal UI |
| Linux or WSL | A compatible shell environment is required |
| `vlc` or `mpv` | Optional; enables local-file and YouTube playback |

> [!NOTE]
> The installer checks for Python, Node.js, and npm, but it does not install
> system packages for you.

## Installation

From the project checkout:

```bash
./scripts/install.sh
```

The installer:

- Creates or reuses `.venv`
- Installs the Python package and dependencies
- Installs the React + Ink TUI dependencies with `npm ci`
- Builds `src/cli-ui/dist/index.js`
- Creates a user-facing `sonex` launcher at `~/.local/bin/sonex`

> [!TIP]
> If `~/.local/bin` is not on your `PATH`, add it to your shell profile and open
> a new shell:

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

## Getting Started

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

## Verify the Installation

Run:

```bash
./scripts/doctor.sh
```

`doctor.sh` checks Python dependencies, Node dependencies, TUI build output, the
`sonex` command, `~/.sonex`, optional local players, and Spotify configuration
status.

## LLM Provider Setup

Sonex stores local credentials under `~/.sonex` by default. Set `SONEX_HOME` if
you want to use a different state directory.

Sonex prefers official provider APIs for the main cloud LLMs:

| Provider | Integration |
| --- | --- |
| OpenAI | Official API Key endpoint, or isolated Codex App Server managed ChatGPT Subscription access (experimental) |
| Anthropic | Official messages endpoint with API Key authentication |
| Google Gemini | Official Gemini API with API Key or Google OAuth and a user-supplied Cloud project (preview) |
| DeepSeek | Official API adapter |
| Custom | Named OpenAI-compatible Chat Completions connections with model discovery and manual Model ID fallback |

Open the only interactive LLM connection entry point inside Sonex:

```text
/login
```

Choose OpenAI, Google Gemini, Anthropic, DeepSeek, or Custom in the panel.
OpenAI API Key and ChatGPT Subscription credentials are independent and never
silently fall back to each other. Google OAuth requires a Cloud project with
Gemini API access and billing already configured. Anthropic OAuth is not
included in V1.

Environment variables are also supported:

```bash
export SONEX_DEFAULT_PROVIDER=openai
export SONEX_DEFAULT_MODEL=gpt-5.5
export SONEX_OPENAI_API_KEY=sk-...
export SONEX_ANTHROPIC_API_KEY=sk-ant-...
export SONEX_GEMINI_API_KEY=...
export SONEX_DEEPSEEK_API_KEY=sk-...
```

> [!WARNING]
> Never commit API keys or saved Sonex credentials to source control. Prefer
> `/login` for local secrets, and provide environment variables through a
> secure local or deployment secret store.

If you start chatting before the default provider is configured, the TUI
opens the same provider panel before planner or agent work begins. The former
built-in Ollama provider is retired and is not migrated automatically. Add
Ollama or another compatible endpoint as a named Custom connection instead.

Sonex loads `.env`, then resolves runtime configuration in this order:
environment variables, saved `/login` credentials, and finally the JSON
config file. Set `SONEX_CONFIG_PATH` to use a config file other than
`~/.sonex/thinking.json`.

Advanced users can still override per-provider `base_url`, `model`,
`timeout`, `extra_headers`, and `options` in `~/.sonex/thinking.json`:

```json
{
  "default_provider": "openai",
  "default_model": "gpt-5.5",
  "providers": {
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-5.5",
      "timeout": 60,
      "extra_headers": {},
      "options": {}
    }
  },
  "beads": {
    "brand": "hama"
  }
}
```

## Music Service Setup

Run `/connect` to open the interactive music-account panel. It lists Spotify,
NetEase Cloud Music, Jamendo, and Audius. Availability checks stay specific to
each service and do not silently change the active playback provider.

> [!NOTE]
> Connection records contain only non-secret account and health metadata.
> OAuth tokens remain with their existing local owners.

> [!NOTE]
> Sonex automatically removes saved `apple_music` and `apple_mode` credentials,
> connection records, and mode intent from its own state. If you previously set
> `SONEX_APPLE_*` environment variables, remove them from your shell profile
> manually. Sonex does not delete external `.p8` files.

### Spotify

In the TUI, type:

```text
/spotify
```

Sonex will guide you through creating a Spotify app, adding the loopback
redirect URI, entering the Client ID and Client Secret, and completing browser
authorization.

Spotify app credentials can come from `SPOTIFY_CLIENT_ID` and
`SPOTIFY_CLIENT_SECRET`, or from the guided TUI setup. Spotify playback control
requires a Spotify account and an available Spotify Connect device; Premium is
required for playback control.

Use `/spotify` to enter persistent Spotify mode after setup. Entry requires a
logged-in Premium account, playback, playlist-read, and `user-library-read`
scopes, and at least one usable Spotify Connect device. After a successful
entry, Sonex restores Spotify mode in later chats until the local Spotify token
expires, loses required scopes, or you run `/spotify` and confirm the exit
panel. Startup restore only checks the local token and saved device
metadata; it does not call Spotify account or device APIs. While the mode is
active, play/search, recommendations, playlists, and current playback use
Spotify tools only. In Spotify mode, `/recommend [taste]` shows five numbered
Spotify recommendations and adds them to your Spotify queue on the selected
device without starting playback. `/playlist` opens the local playlist browser
immediately, then refreshes Spotify mirrors in the background only when the
persisted mirror is stale. Saved tracks are incrementally merged between
weekly full reconciliations, and unchanged playlists are skipped by Spotify
snapshot ID. Successful mirrors remain fresh for six hours; connection failures
back off for at least fifteen minutes, or for Spotify's longer `Retry-After`.
Normal Sonex mode can still browse imported Spotify mirrors, but
`/playlist save` only writes to editable Sonex playlists.
`/queue` opens your live Spotify playback queue. If Spotify returns `429 Too
Many Requests`, Sonex preserves the reported retry timing and does not repeat
the synchronization burst during that cooldown. Proxy, connection, TLS, and
read-timeout failures are reported separately. If the saved token is missing
newly required Spotify scopes, Sonex starts the Spotify authorization guide in
the current chat so you can grant the updated permissions.

### Local and YouTube Playback

Install `mpv` or VLC if you want controllable local-file or online playback.
The first `/player` call in a session detects installed applications supported
by Sonex. Managed mpv/VLC and supported external applications such as
Clementine, Rhythmbox, and Audacious can become the device default. Other
running MPRIS applications remain visible as remote-control-only when they
cannot accept audio. Spotify Connect remains a separate provider mode and does
not use these local players.

### Online Audio Fallback

In normal mode, Sonex uses local files first and then resolves selected songs
through online audio sources. Spotify playback belongs to Spotify Mode.
iTunes Search remains part of metadata discovery in the normal search chain; it
is not a playback mode. Configure at least one online audio provider:

Use `/connect` and choose Jamendo or Audius.

You can also provide credentials through environment variables:

```bash
export SONEX_JAMENDO_CLIENT_ID=...
export SONEX_AUDIUS_API_KEY=...
```

The resolver keeps the selected song identity separate from provider metadata,
revalidates cached audio, and shows provider fallback reasons in the TUI when a
candidate cannot be used.

## Playback Tutorial

Use a natural-language play request:

```text
play Space Oddity David Bowie
play Mitski Nobody
播放 方大同 忘了美丽
```

Sonex checks for a matching local file first. Without a local match, or after you
skip it, normal mode opens up to five metadata candidates and continues through
Sonex online audio without asking for a playback provider. `/recommend [taste]`
returns a numbered text list first, defaults to
five tracks, uses the hint before recent playback and `USER.md` preferences, and
adds the recommended tracks to the Sonex playback queue without starting
playback. You can then ask to play an item such as `play number 2` or `播放第2首`.

While a local or online track is playing, use:

```text
/pause
/resume
/stop
/progress
/volume 65
/player
```

`/player` detects supported installed applications on its first call in the
session and opens a default-player panel. After you choose a compatible player,
local and online-audio playback uses that device-persistent default directly
without asking you to choose again. Cancel keeps the current default unchanged.

## Cover Bead Art

The TUI can render album covers as static physical-bead patterns. Sonex uses the
official cover image when one is available, then generates cached square variants
at `40x40`, `48x48`, `56x56`, `64x64`, `80x80`, and `96x96`. The current algorithm uses a shared, no-dither
palette of 32 to 72 colors, weighted toward the 80 and 96 preview sizes, and
invalidates older cache profiles automatically.

Supported bead catalogs are 5 mm Hama Midi, Perler Classic, and Mard Standard
Opaque. Mard color identities follow the bundled official brand reference, while
the RGB approximation remains sourced from the redistributable community
`beadcolors` catalog. Configure the brand in `~/.sonex/thinking.json` or the file pointed to by `SONEX_CONFIG_PATH`:

```json
{
  "beads": {
    "brand": "perler"
  }
}
```

If `beads.brand` is omitted, Sonex uses `hama`. Generated patterns are stored
under `~/.sonex/cache/cover_patterns` and the original cover image bytes are not
stored in that cache.

## Troubleshooting

- **`sonex: command not found`:** Make sure `~/.local/bin` is on `PATH`, then run
  `./scripts/doctor.sh`.
- **A different `sonex` command is found:** Run
  `./scripts/install.sh --force-user-shim` for this checkout.
- **Runtime files are missing:** Run `sonex` again; the bootstrap launcher can
  repair `.venv`, TUI dependencies, and the built TUI. You can also rerun
  `./scripts/install.sh`.
- **The TUI says the API is not running:** Launch with `sonex`, or run `sonex api`
  before `sonex tui` when debugging.
- **Spotify cannot play:** Follow the TUI reauthorization guide when scopes are
  missing, or open `/spotify` and reconnect. Check account product and
  make sure Spotify is open on a device.
- **Local or online playback cannot start:** Install `mpv` or VLC, start a new
  session, run `/player`, and choose one of the detected applications.
- **Cover bead art does not appear:** Check `beads.brand`, rerun playback with an
  official cover source, and inspect `~/.sonex/log` for cover generation errors.
