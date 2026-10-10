# Sonex Web

The browser UI runs against one local Sonex process. The process owns the Agent, sessions, confirmations, player, queue, and music library; browser tabs can reconnect without restarting those tasks.

## Build and run

Build the React Web UI assets once, install Sonex, then start the local service:

```bash
npm --prefix src/web/frontend ci
npm --prefix src/web/frontend run build
python -m pip install -e .
sonex web
```

The server binds only to `127.0.0.1:9002`, opens the browser, and stays in the foreground. Use `Ctrl+C` to stop it. WSL users can open `http://localhost:9002` from Windows; native Windows can run the same command in PowerShell after building the frontend assets.

Music library paths are entered in the browser but resolved by the Runtime. Use a Linux path under WSL and a Windows path for a native Windows Runtime. Sonex scans up to 500 audio files and plays the selected file with mpv without copying it.

The browser UI and build tools live in `src/web/frontend`; no Rust or Tauri toolchain is needed. Built files in `src/web/static` are included in Python package builds. Rebuild them after changing the UI. For live UI work, run `sonex web` in one terminal and `npm --prefix src/web/frontend run dev` in another. The web server accepts WebSocket connections only from its same-origin loopback page.
