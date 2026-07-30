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

The installer checks for Python, Node.js, and npm, but it does not install
system packages for you.

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
| OpenAI | Official chat completions endpoint |
| Anthropic | Official messages endpoint |
| Gemini | Official generate content endpoint, including OAuth headers when configured |
| DeepSeek | Official API adapter |
| LiteLLM | Installed as a compatibility fallback for custom or not-yet-native providers; not the default path for the cloud providers above |

Manage LLM provider credentials with:

```bash
sonex auth login openai
sonex auth set-key openai
sonex auth list
sonex auth set-default openai
sonex auth logout openai
```

Environment variables are also supported:

```bash
export SONEX_DEFAULT_PROVIDER=openai
export SONEX_DEFAULT_MODEL=gpt-5.5
export SONEX_OPENAI_API_KEY=sk-...
export SONEX_ANTHROPIC_API_KEY=sk-ant-...
export SONEX_GEMINI_API_KEY=...
export SONEX_DEEPSEEK_API_KEY=sk-...
```

If you start chatting before the default provider is configured, the TUI
starts an interactive setup flow before planner or agent work begins. `ollama`
can be used as a local provider when configured as the default provider.

Sonex loads `.env`, then resolves runtime configuration in this order:
environment variables, saved `sonex auth` credentials, and finally the JSON
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

Run `/connect` to open the interactive music-account panel. The first release
offers Spotify and Apple Music because Sonex can complete their supported
authorization flows. Connection records contain only non-secret account and
health metadata; OAuth tokens and MusicKit authorization remain with their
existing local owners. NetEase Cloud Music is not listed until the official
`ncm-cli` adapter is implemented and validated.

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

### Apple Music

Apple Mode obtains short-lived developer tokens from a token service. Configure
the service URL from the terminal, then enter Apple Mode:

Run `/connect`, choose Apple Music, then run `/apple`.

The environment variable remains available and takes precedence over the saved
terminal configuration:

```bash
export SONEX_APPLE_TOKEN_BROKER_URL=https://tokens.example.com
```

Developer tokens remain in memory, while MusicKit keeps the Music User Token in
the local browser companion. Advanced local development can explicitly select
the local signer with `SONEX_APPLE_TOKEN_SOURCE=local` and configure signing
credentials with `sonex auth set-key apple_music --api-key '<json-or-path>'`.

### Local and YouTube Playback

Install `mpv` or VLC if you want controllable local-file or online playback.
The first `/player` call in a session detects installed applications supported
by Sonex. Managed mpv/VLC and supported external applications such as
Clementine, Rhythmbox, and Audacious can become the device default. Other
running MPRIS applications remain visible as remote-control-only when they
cannot accept audio. Spotify Connect and Apple Music remain separate provider
modes and do not use these local players.

### Online Audio Fallback

In normal mode, Sonex uses local files first and then resolves selected songs
through online audio sources. Spotify playback belongs to Spotify Mode; Apple
Music playback belongs to Apple Mode. Configure at least one online audio
provider:

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
  missing, or run `sonex auth login spotify` again. Check account product and
  make sure Spotify is open on a device.
- **Local or online playback cannot start:** Install `mpv` or VLC, start a new
  session, run `/player`, and choose one of the detected applications.
- **Cover bead art does not appear:** Check `beads.brand`, rerun playback with an
  official cover source, and inspect `~/.sonex/log` for cover generation errors.
