# Sonex Desktop

Windows-first personal Agent music player, built with Tauri 2, React and the shared Python Sonex Runtime. This is the initial desktop implementation, not a signed release.

The left rail contains local sessions, music library, memory, extensions and user settings. The center hosts the Agent conversation and existing authorization flows. The right rail holds the global player and editable upcoming queue. Closing the window hides it to the tray; choose **退出 Sonex** from the tray to exit.

## Run from source

Development requires Node.js 22.12+ (24 recommended), Python 3.12+, Rust and the [Tauri platform prerequisites](https://v2.tauri.app/start/prerequisites/). On Windows these include the MSVC build tools and WebView2. Install mpv on PATH for local playback.

From the repository root, create `.venv` and install the Python project and desktop dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e . pytest
npm --prefix src/desktop ci
npm --prefix src/desktop run dev
```

On Linux use `.venv/bin/python` for Python commands. Linux is a development host; the first installer targets Windows. `npm --prefix src/desktop run dev:web` previews the frontend in a browser, with an explicit disconnected state. Only the Tauri host starts and communicates with the Runtime.

## Architecture decisions

| Decision | Implementation and tradeoff |
| --- | --- |
| Shared Runtime | `runtime/runner.py` extends the existing message router and UI adapter. Agent tools, provider authentication, memory, playlists and playback remain in shared Python modules. CLI continues using WebSocket. |
| Host-owned subprocess | React invokes two scoped Rust commands. Rust owns a Python subprocess and exchanges bounded, newline-delimited JSON over stdio. No listening TCP port, shell API or credentials in command arguments. Tauri Channels carry events back to React. |
| Multiple histories, one active Agent | Browsing another session does not interrupt the active task or player. Sending to another session switches execution context only when the current task and confirmations have completed. `session_id` on events prevents cross-session rendering. |
| Global playback | One shared mpv controller and persistent `up_next` queue. Queue edits use the existing revision check. Natural playback completion advances through the shared queue selection path; new playback or an explicit stop supersedes auto-advance. Spotify mode delegates its transport controls to the existing provider implementation. |
| Local persistence | Transcript snapshots are atomically saved after chat events in the existing `sessions/<id>/transcript.jsonl` format. The first release lists the latest 100 sessions. Larger history pagination and long-transcript virtualization are follow-up work. |
| Native process lifetime | Single-instance host, tray and Windows Job Object cleanup. The host closes stdin on explicit exit, gives the Runtime time to shut down, then terminates remaining managed processes. Reloading the WebView reconnects the event channel and requests a snapshot. |

```text
React interface
    ↕ Tauri invoke / Channel
Rust host (window, tray, process lifetime)
    ↕ JSON lines over stdin / stdout
Desktop transport → shared Sonex Agent, tools, memory, providers
                                  ↕
                             shared mpv controller
```

Both CLI (`src/cli`) and Desktop use `Path.home() / '.sonex'`, or the explicit `SONEX_HOME` override. On Windows this normally means `C:\Users\<user>\.sonex`. The shell does not create a second app configuration store. WebView engine caches are separate OS-managed application data. Model and online music requests go directly through the configured providers; local UI, histories and local playback do not require a Sonex cloud account.

## Windows packaging

Build on Windows after setting up the development prerequisites:

```powershell
.venv\Scripts\python -m pip install pyinstaller
.\src\desktop\packaging\build-windows.ps1 -PlayerDirectory C:\path\to\mpv-distribution
```

Supply a Windows mpv distribution containing `mpv.exe`, its required DLLs and license notices. The script builds a PyInstaller **onedir** runtime, preserves its `_internal` directory, adds the player distribution and produces a per-user NSIS installer. Python and frontend build tools are not required on the installed machine. The default WebView2 bootstrapper needs a network connection when WebView2 is missing; an offline installer can change `webviewInstallMode` to `offlineInstaller`.

Provider-specific helper runtimes such as the optional YouTube extension still follow the shared Runtime's dependency setup. They are not implicitly included by the base desktop packaging script.

## Verification

```text
npm --prefix src/desktop run build:web
npm --prefix src/desktop test
.venv/bin/python -m pytest -q tests/test_desktop_runtime.py tests/test_playback_controller.py tests/test_builtin_command_runner.py
cargo check --manifest-path src/desktop/src-tauri/Cargo.toml
```

The Windows CI workflow checks the frontend, Python regression tests and native Rust build. It does not certify real audio devices or a release installer. Before release, verify installation on a clean Windows machine, real playback and seeking, tray exit, Chinese and spaced paths, sleep/resume, provider callbacks and process cleanup.

Current boundaries: one foreground Agent task, latest 100 sessions, local seek/volume only (Spotify seek/volume stay in Spotify), no local-player previous-track history, no OS media-key integration, and no signed automatic updater. Native packaging and real Windows playback require Windows validation.
