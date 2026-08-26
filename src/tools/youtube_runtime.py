"""Managed YouTube runtime, provider lifecycle, and cross-process request gates.

The normal Sonex environment deliberately does not install or update YouTube
plugins in the application virtualenv.  This module owns the small state
machine around a user-authorized runtime bundle and keeps the real YouTube
worker path fail-closed when no verified bundle is active.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from src.log import sonex_home

try:  # pragma: no cover - exercised on the supported POSIX targets
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


RUNTIME_FORMAT = 1
PROVIDER_IDLE_SECONDS = 6 * 60 * 60
UPDATE_CHECK_TTL_SECONDS = 24 * 60 * 60
UPDATE_COOLDOWN_SECONDS = 6 * 60 * 60
UPDATE_TOTAL_TIMEOUT_SECONDS = 20 * 60
REQUEST_QUEUE_TIMEOUT_SECONDS = 75.0
REQUEST_MIN_INTERVAL_SECONDS = 3.0
DEFAULT_PROVIDER_REPO = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"

_health_check_lock = threading.Lock()
_health_check_started_for: str | None = None
PYPI_BASE = "https://pypi.org/pypi"


class YoutubeRuntimeError(RuntimeError):
    """Base error for the managed YouTube runtime."""

    code = "YOUTUBE_RUNTIME_ERROR"


class YoutubeRuntimeUnavailable(YoutubeRuntimeError):
    """Raised when the verified runtime/provider is not usable."""

    code = "YOUTUBE_PO_PROVIDER_UNAVAILABLE"


class YoutubeQueueBusy(YoutubeRuntimeError):
    """Raised when the cross-process YouTube request queue times out."""

    code = "YOUTUBE_QUEUE_BUSY"


def runtime_root() -> Path:
    return sonex_home() / "runtimes" / "youtube"


def state_root() -> Path:
    return sonex_home() / "youtube-runtime"


def _state_path(name: str) -> Path:
    return state_root() / name


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _mkdir(path.parent)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


@contextlib.contextmanager
def _exclusive_file_lock(path: Path, *, timeout: float) -> Iterator[None]:
    """Acquire a user-owned cross-process lock with a bounded wait."""

    _mkdir(path.parent)
    handle = path.open("a+")
    started = time.monotonic()
    acquired = False
    try:
        while time.monotonic() - started < max(0.01, timeout):
            if fcntl is None:
                acquired = True
                break
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.1)
        if not acquired:
            raise YoutubeQueueBusy("YouTube request queue is busy; try again later.")
        yield
    finally:
        if acquired and fcntl is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _normalize_proxy(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "direct"
    try:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(text)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme.lower(), f"{host.lower()}{port}", parsed.path, "", ""))
    except ValueError:
        return "proxy"


def _proxy_from_options(options: dict[str, Any]) -> str:
    return _normalize_proxy(options.get("proxy") or options.get("http_proxy"))


@contextlib.contextmanager
def youtube_request_gate(
    *,
    options: dict[str, Any],
    timeout: float = REQUEST_QUEUE_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize uncached YouTube work per normalized egress identity."""

    identity = _normalize_proxy(_proxy_from_options(options))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    lock_path = state_root() / "requests" / f"{digest}.lock"
    state_path = state_root() / "requests" / f"{digest}.json"
    with _exclusive_file_lock(lock_path, timeout=timeout):
        state = _read_json(state_path) or {}
        last_started = float(state.get("last_started_at") or 0.0)
        wait_for = REQUEST_MIN_INTERVAL_SECONDS - (time.time() - last_started)
        if wait_for > 0:
            time.sleep(min(wait_for, max(0.01, timeout)))
        _write_json(
            state_path,
            {"egress": identity, "last_started_at": time.time()},
        )
        yield


def _active_manifest_path() -> Path:
    return runtime_root() / "active.json"


def _pending_manifest_path() -> Path:
    return runtime_root() / "pending.json"


def active_manifest() -> dict[str, Any] | None:
    payload = _read_json(_active_manifest_path())
    if not payload or int(payload.get("format") or 0) != RUNTIME_FORMAT:
        return None
    return payload


def pending_manifest() -> dict[str, Any] | None:
    return _read_json(_pending_manifest_path())


def cleanup_old_runtimes() -> None:
    """Retain active/previous/pending bundles and remove older payloads."""
    versions_dir = runtime_root() / "versions"
    if not versions_dir.is_dir():
        return
    keep = {
        str((active_manifest() or {}).get("runtime_id") or ""),
        str((_read_json(runtime_root() / "previous.json") or {}).get("runtime_id") or ""),
        str((pending_manifest() or {}).get("runtime_id") or ""),
    }
    provider = _provider_state()
    if provider and provider.get("runtime_id"):
        keep.add(str(provider["runtime_id"]))
    for candidate in versions_dir.iterdir():
        if not candidate.is_dir() or candidate.name in keep:
            continue
        with contextlib.suppress(OSError):
            shutil.rmtree(candidate)


def activate_pending_runtime() -> bool:
    """Atomically activate a candidate at the next application session."""

    current_state = _read_json(_state_path("state.json")) or {}
    if current_state.get("rollback_pending"):
        previous = _read_json(runtime_root() / "previous.json")
        provider = _provider_state()
        if provider and provider.get("runtime_id") != (previous or {}).get("runtime_id"):
            _terminate_pid(int(provider.get("monitor_pid") or 0))
            with contextlib.suppress(FileNotFoundError):
                _state_path("provider.json").unlink()
        if previous:
            _write_json(_active_manifest_path(), previous)
        with contextlib.suppress(FileNotFoundError):
            _pending_manifest_path().unlink()
        _write_json(
            _state_path("state.json"),
            {
                "status": "ready" if previous else "setup_required",
                "runtime_id": (previous or {}).get("runtime_id"),
                "rollback_applied_at": time.time(),
                "probation": False,
            },
        )
        _write_json(_state_path("update.json"), {"status": "idle", "phase": "rollback_applied"})
        cleanup_old_runtimes()
        return previous is not None

    candidate = pending_manifest()
    if not candidate:
        return False
    bundle = Path(str(candidate.get("bundle_path") or "")).expanduser()
    python_path = Path(str(candidate.get("python_executable") or "")).expanduser()
    server_path = Path(str(candidate.get("server_entry") or "")).expanduser()
    if not bundle.is_dir() or not python_path.is_file() or not server_path.is_file():
        return False
    provider = _provider_state()
    if provider and provider.get("runtime_id") != candidate.get("runtime_id"):
        _terminate_pid(int(provider.get("monitor_pid") or 0))
        with contextlib.suppress(FileNotFoundError):
            _state_path("provider.json").unlink()
    previous = active_manifest()
    if previous:
        _write_json(runtime_root() / "previous.json", previous)
    _write_json(_active_manifest_path(), candidate)
    with contextlib.suppress(FileNotFoundError):
        _pending_manifest_path().unlink()
    _write_json(
        _state_path("state.json"),
        {
            "status": "ready",
            "runtime_id": candidate.get("runtime_id"),
            "yt_dlp_version": candidate.get("yt_dlp_version"),
            "provider_version": candidate.get("provider_version"),
            "activated_at": time.time(),
            "probation": True,
        },
    )
    _write_json(
        _state_path("update.json"),
        {"status": "idle", "phase": "activated", "activated_runtime_id": candidate.get("runtime_id")},
    )
    cleanup_old_runtimes()
    return True


def mark_runtime_success() -> None:
    state = _read_json(_state_path("state.json")) or {}
    if not state.get("probation"):
        return
    _write_json(
        _state_path("state.json"),
        {
            **state,
            "status": "ready",
            "probation": False,
            "known_good_runtime_id": (active_manifest() or {}).get("runtime_id"),
            "last_success_at": time.time(),
        },
    )


def mark_runtime_failure(reason: str) -> None:
    state = _read_json(_state_path("state.json")) or {}
    if not state.get("probation"):
        return
    _write_json(
        _state_path("state.json"),
        {
            **state,
            "status": "degraded",
            "rollback_pending": True,
            "rollback_reason": str(reason)[:160],
            "probation": False,
        },
    )


def _provider_state() -> dict[str, Any] | None:
    return _read_json(_state_path("provider.json"))


def _provider_log_path() -> Path:
    _mkdir(state_root() / "logs")
    return state_root() / "logs" / "provider.log"


def _provider_ping(base_url: str, timeout: float = 0.5) -> bool:
    try:
        request = urllib.request.Request(f"{base_url}/ping", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate_pid(pid: int | None) -> None:
    if not _pid_alive(pid):
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.05)
    if _pid_alive(pid):
        with contextlib.suppress(OSError):
            os.kill(int(pid), signal.SIGKILL)


def _ensure_provider_running_locked(manifest: dict[str, Any]) -> str:
    manifest = manifest or active_manifest()
    if not manifest:
        raise YoutubeRuntimeUnavailable("YouTube PO Token Provider is not set up. Run `sonex youtube setup`.")
    provider = _provider_state()
    if provider:
        base_url = str(provider.get("base_url") or "")
        if _pid_alive(int(provider.get("monitor_pid") or 0)) and _provider_ping(base_url):
            _write_json(
                _state_path("provider.json"),
                {**provider, "last_activity_at": time.time()},
            )
            return base_url
        _terminate_pid(int(provider.get("monitor_pid") or 0))
        with contextlib.suppress(FileNotFoundError):
            _state_path("provider.json").unlink()

    node = str(manifest.get("node_executable") or shutil.which("node") or "")
    server_entry = Path(str(manifest.get("server_entry") or ""))
    if not node or not server_entry.is_file():
        raise YoutubeRuntimeUnavailable("The managed PO Token Provider runtime is incomplete. Run `sonex youtube repair`.")
    port = _pick_port()
    command = [
        sys.executable,
        "-m",
        "src.tools.youtube_runtime",
        "--provider-monitor",
        str(server_entry),
        node,
        str(port),
    ]
    _mkdir(state_root())
    monitor = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    provider_payload = {
        "monitor_pid": monitor.pid,
        "port": port,
        "base_url": f"http://127.0.0.1:{port}",
        "runtime_id": manifest.get("runtime_id"),
        "started_at": time.time(),
        "last_activity_at": time.time(),
    }
    _write_json(_state_path("provider.json"), provider_payload)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _provider_ping(str(provider_payload["base_url"])):
            return str(provider_payload["base_url"])
        if monitor.poll() is not None:
            break
        time.sleep(0.1)
    _terminate_pid(monitor.pid)
    with contextlib.suppress(FileNotFoundError):
        _state_path("provider.json").unlink()
    raise YoutubeRuntimeUnavailable("The managed PO Token Provider did not become healthy.")


def ensure_provider_running(manifest: dict[str, Any] | None = None) -> str:
    """Start or reuse the detached provider monitor and return its base URL."""

    resolved = manifest or active_manifest()
    if not resolved:
        raise YoutubeRuntimeUnavailable("YouTube PO Token Provider is not set up. Run `sonex youtube setup`.")
    with _exclusive_file_lock(state_root() / "provider.lock", timeout=10.0):
        return _ensure_provider_running_locked(resolved)


def _provider_monitor(server_entry: str, node: str, port: int) -> int:
    log_path = _provider_log_path()
    with log_path.open("a", encoding="utf-8") as log:
        child = subprocess.Popen(
            [node, server_entry, "--port", str(port)],
            cwd=str(Path(server_entry).parent.parent),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        monitor_started = time.monotonic()
        try:
            while child.poll() is None:
                state = _provider_state()
                if not state:
                    # The parent writes provider.json immediately after this
                    # detached monitor is spawned. Allow that handoff to win
                    # before treating a missing file as a shutdown request.
                    if time.monotonic() - monitor_started < 5.0:
                        time.sleep(0.1)
                        continue
                    break
                last_activity = float(state.get("last_activity_at") or time.time())
                if time.time() - last_activity >= PROVIDER_IDLE_SECONDS:
                    _terminate_pid(child.pid)
                    break
                time.sleep(10.0)
        finally:
            _terminate_pid(child.pid)
            state = _provider_state()
            if state and int(state.get("monitor_pid") or 0) == os.getpid():
                with contextlib.suppress(FileNotFoundError):
                    _state_path("provider.json").unlink()
    return 0


def prepare_worker(
    options: dict[str, Any],
    *,
    operation: str = "download",
) -> tuple[dict[str, Any], str]:
    """Prepare safe yt-dlp options and the provider URL for one real request."""

    manifest = active_manifest()
    if not manifest:
        raise YoutubeRuntimeUnavailable("YouTube PO Token Provider is not set up. Run `sonex youtube setup`.")
    if (_read_json(_state_path("state.json")) or {}).get("rollback_pending"):
        raise YoutubeRuntimeUnavailable("The active YouTube runtime failed probation and is awaiting rollback. Restart Sonex.")
    safe_options = dict(options)
    safe_options["ignoreconfig"] = True
    for forbidden in ("cookiefile", "cookiesfrombrowser", "http_headers", "headers"):
        safe_options.pop(forbidden, None)
    if operation in {"resolve", "download"}:
        provider_url = ensure_provider_running(manifest)
        extractor_args = dict(safe_options.get("extractor_args") or {})
        youtube_args = dict(extractor_args.get("youtube") or {})
        youtube_args["player_client"] = ["mweb"]
        extractor_args["youtube"] = youtube_args
        pot_args = dict(extractor_args.get("youtubepot-bgutilhttp") or {})
        pot_args["base_url"] = [provider_url]
        extractor_args["youtubepot-bgutilhttp"] = pot_args
        safe_options["extractor_args"] = extractor_args
    else:
        provider_url = ""
    return safe_options, provider_url


def worker_command() -> list[str]:
    manifest = active_manifest()
    if not manifest:
        return [sys.executable, "-m", "src.tools.yt_dlp_worker"]
    python_path = Path(str(manifest.get("python_executable") or ""))
    if not python_path.is_file():
        raise YoutubeRuntimeUnavailable("The active YouTube runtime interpreter is missing.")
    return [str(python_path), "-m", "src.tools.yt_dlp_worker"]


def worker_env() -> dict[str, str]:
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[2])
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{current}" if current else project_root
    env.pop("PYTHONSTARTUP", None)
    return env


def local_runtime_check(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check the managed files and package entry points without network I/O."""
    manifest = manifest or active_manifest()
    if not manifest:
        return {"healthy": False, "reason": "setup_required"}
    python_path = Path(str(manifest.get("python_executable") or ""))
    server_path = Path(str(manifest.get("server_entry") or ""))
    if not python_path.is_file() or not server_path.is_file():
        return {"healthy": False, "reason": "runtime_files_missing"}
    try:
        subprocess.run(
            [
                str(python_path),
                "-c",
                "import importlib.metadata, yt_dlp; importlib.metadata.version('bgutil-ytdlp-pot-provider')",
            ],
            cwd=Path(str(manifest.get("bundle_path") or python_path.parent)),
            env=worker_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=3,
        )
        node = str(manifest.get("node_executable") or shutil.which("node") or "")
        if node:
            subprocess.run(
                [node, "--version"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=3,
            )
    except (OSError, subprocess.SubprocessError):
        return {"healthy": False, "reason": "runtime_entrypoint_check_failed"}
    return {"healthy": True, "reason": "ok"}


def runtime_status() -> dict[str, Any]:
    manifest = active_manifest()
    state = _read_json(_state_path("state.json")) or {}
    provider = _provider_state()
    if not manifest:
        status = "setup_required"
    elif state.get("status") == "degraded":
        status = "degraded"
    elif pending_manifest():
        status = "restart_required"
    else:
        status = str(state.get("status") or "ready")
    provider_running = bool(
        provider
        and _pid_alive(int(provider.get("monitor_pid") or 0))
        and _provider_ping(str(provider.get("base_url") or ""))
    )
    return {
        "status": status,
        "provider_runtime": "running" if provider_running else "stopped",
        "runtime_id": manifest.get("runtime_id") if manifest else None,
        "yt_dlp_version": manifest.get("yt_dlp_version") if manifest else None,
        "provider_version": manifest.get("provider_version") if manifest else None,
        "pending_runtime_id": (pending_manifest() or {}).get("runtime_id"),
        "local_check": state.get("local_check") or {"healthy": bool(manifest)},
        "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
        "state_path": str(_state_path("state.json")),
    }


def _pypi_latest(package: str) -> str | None:
    request = urllib.request.Request(
        f"{PYPI_BASE}/{package}/json",
        headers={"Accept": "application/json", "User-Agent": "Sonex/1.0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return str(version) if version else None


def _pypi_wheel_hash(package: str, version: str) -> str:
    request = urllib.request.Request(
        f"{PYPI_BASE}/{package}/{version}/json",
        headers={"Accept": "application/json", "User-Agent": "Sonex/1.0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    urls = payload.get("urls") if isinstance(payload, dict) else None
    if not isinstance(urls, list):
        raise RuntimeError(f"PyPI release metadata is missing for {package} {version}")
    for item in urls:
        if not isinstance(item, dict) or not str(item.get("filename") or "").endswith(".whl"):
            continue
        digest = item.get("digests")
        if isinstance(digest, dict) and digest.get("sha256"):
            return str(digest["sha256"])
    raise RuntimeError(f"No attested wheel found for {package} {version}")


def _versions_cache() -> Path:
    return state_root() / "version-check.json"


def latest_versions(*, force: bool = False) -> dict[str, Any]:
    cached = _read_json(_versions_cache())
    if cached and not force and time.time() - float(cached.get("checked_at") or 0) < UPDATE_CHECK_TTL_SECONDS:
        return cached
    result: dict[str, Any] = {"checked_at": time.time()}
    for key, package in (
        ("yt_dlp_version", "yt-dlp"),
        ("provider_version", "bgutil-ytdlp-pot-provider"),
    ):
        try:
            result[key] = _pypi_latest(package)
        except Exception as exc:
            result[f"{key}_error"] = type(exc).__name__
    _write_json(_versions_cache(), result)
    return result


def _version_tuple(value: Any) -> tuple[int, ...]:
    parts: list[int] = []
    for part in str(value or "").split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _is_newer(candidate: Any, current: Any) -> bool:
    left = _version_tuple(candidate)
    right = _version_tuple(current)
    return bool(left and right and left > right)


def _same_provider_major(candidate: Any, current: Any) -> bool:
    left = _version_tuple(candidate)
    right = _version_tuple(current)
    return bool(left and right and left[0] == right[0])


def _update_state(**values: Any) -> dict[str, Any]:
    state = _read_json(_state_path("update.json")) or {}
    state.update(values)
    _write_json(_state_path("update.json"), state)
    return state


def update_state() -> dict[str, Any]:
    return _read_json(_state_path("update.json")) or {"status": "idle"}


def start_update_job(*, reason: str = "setup", force: bool = False) -> dict[str, Any]:
    current = update_state()
    if current.get("status") == "running" and _pid_alive(int(current.get("pid") or 0)):
        return current
    if not force and float(current.get("retry_after") or 0) > time.time():
        return current
    _mkdir(state_root())
    payload = _update_state(
        status="running",
        reason=reason,
        started_at=time.time(),
        pid=0,
        phase="queued",
        error=None,
    )
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "src.tools.youtube_runtime", "--update-worker"],
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        _update_state(status="failed", phase="spawn_failed", error=type(exc).__name__, retry_after=time.time() + UPDATE_COOLDOWN_SECONDS)
        raise
    payload["pid"] = process.pid
    return _update_state(**payload)


def _run_checked(command: list[str], *, cwd: Path, timeout: float, phase: str) -> None:
    _update_state(phase=phase)
    started_at = float((_read_json(_state_path("update.json")) or {}).get("started_at") or time.time())
    remaining = UPDATE_TOTAL_TIMEOUT_SECONDS - (time.time() - started_at)
    if remaining <= 0:
        raise TimeoutError("YouTube updater exceeded its 20-minute total budget.")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=worker_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        process.communicate(timeout=min(max(1.0, timeout), remaining))
    except subprocess.TimeoutExpired as exc:
        if os.name != "nt":
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        with contextlib.suppress(Exception):
            process.communicate(timeout=2)
        raise TimeoutError(f"YouTube updater phase {phase} timed out.") from exc
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def _patch_bgutil_server(source: Path) -> str:
    original = source.read_text(encoding="utf-8")
    patched = original.replace('host: "::",', 'host: "127.0.0.1",')
    patched = patched.replace('host: "0.0.0.0",', 'host: "127.0.0.1",')
    if patched == original or 'host: "0.0.0.0",' in patched:
        raise RuntimeError("bgutil server localhost patch did not apply cleanly")
    source.write_text(patched, encoding="utf-8")
    return hashlib.sha256(patched.encode("utf-8")).hexdigest()


def _perform_update() -> None:
    started = time.time()
    previous = active_manifest()
    try:
        versions = latest_versions(force=True)
        yt_version = str(versions.get("yt_dlp_version") or "")
        provider_version = str(versions.get("provider_version") or "")
        if not yt_version or not provider_version:
            raise RuntimeError("Stable yt-dlp/provider versions could not be resolved.")
        yt_hash = _pypi_wheel_hash("yt-dlp", yt_version)
        provider_hash = _pypi_wheel_hash("bgutil-ytdlp-pot-provider", provider_version)
        if platform.system().lower() != "linux" or platform.machine().lower() not in {"x86_64", "amd64", "aarch64", "arm64"}:
            raise RuntimeError("Managed YouTube runtime currently supports Linux x64/arm64 and WSL2 only.")
        node_path = shutil.which("node")
        if shutil.which("git") is None or shutil.which("npm") is None or not node_path:
            raise RuntimeError("YouTube setup requires git, npm, and Node.js >= 20.")
        node_version = subprocess.check_output([node_path, "--version"], text=True, timeout=5).strip()
        try:
            node_major = int(node_version.lstrip("v").split(".", 1)[0])
        except (TypeError, ValueError):
            node_major = 0
        if node_major < 20:
            raise RuntimeError("YouTube setup requires Node.js >= 20.")
        _mkdir(runtime_root() / "staging")
        staging = Path(tempfile.mkdtemp(prefix="candidate-", dir=str(runtime_root() / "staging")))
        try:
            venv = staging / "venv"
            _run_checked([sys.executable, "-m", "venv", str(venv)], cwd=staging, timeout=120, phase="create_venv")
            python_path = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            _run_checked(
                [
                    str(python_path),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--only-binary=:all:",
                    f"yt-dlp=={yt_version}",
                    f"--hash=sha256:{yt_hash}",
                    f"bgutil-ytdlp-pot-provider=={provider_version}",
                    f"--hash=sha256:{provider_hash}",
                ],
                cwd=staging,
                timeout=120,
                phase="install_python_runtime",
            )
            source_dir = staging / "bgutil-ytdlp-pot-provider"
            _run_checked(
                ["git", "clone", "--depth", "1", "--branch", provider_version, DEFAULT_PROVIDER_REPO, str(source_dir)],
                cwd=staging,
                timeout=60,
                phase="download_provider_source",
            )
            source_file = source_dir / "server" / "src" / "main.ts"
            patch_hash = _patch_bgutil_server(source_file)
            _run_checked(["npm", "ci"], cwd=source_dir / "server", timeout=12 * 60, phase="install_provider_server")
            _run_checked(["npx", "tsc"], cwd=source_dir / "server", timeout=3 * 60, phase="build_provider_server")
            server_entry = source_dir / "server" / "build" / "main.js"
            if not server_entry.is_file():
                raise RuntimeError("Provider build did not produce server/build/main.js")
            runtime_id = f"yt-dlp-{yt_version}-bgutil-{provider_version}-{int(time.time())}"
            bundle = runtime_root() / "versions" / runtime_id
            _mkdir(bundle.parent)
            shutil.move(str(staging), str(bundle))
            staging = bundle
            manifest = {
                "format": RUNTIME_FORMAT,
                "runtime_id": runtime_id,
                "bundle_path": str(bundle),
                "python_executable": str(bundle / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
                "yt_dlp_version": yt_version,
                "yt_dlp_wheel_sha256": yt_hash,
                "provider_version": provider_version,
                "provider_wheel_sha256": provider_hash,
                "provider_repo": DEFAULT_PROVIDER_REPO,
                "provider_commit": subprocess.check_output(["git", "-C", str(bundle / "bgutil-ytdlp-pot-provider"), "rev-parse", "HEAD"], text=True).strip(),
                "server_entry": str(bundle / "bgutil-ytdlp-pot-provider" / "server" / "build" / "main.js"),
                "node_executable": node_path,
                "localhost_patch_sha256": patch_hash,
                "created_at": time.time(),
            }
            _write_json(bundle / "manifest.json", manifest)
            _write_json(_pending_manifest_path(), manifest)
            _update_state(
                status="ready",
                phase="restart_required",
                completed_at=time.time(),
                candidate_runtime_id=runtime_id,
                candidate_yt_dlp_version=yt_version,
                previous_yt_dlp_version=(previous or {}).get("yt_dlp_version"),
                previous_runtime_id=(previous or {}).get("runtime_id"),
                restart_required=True,
            )
        finally:
            if staging.exists() and staging.parent.name == "staging":
                shutil.rmtree(staging, ignore_errors=True)
    except Exception as exc:
        _update_state(
            status="failed",
            phase="failed",
            error=type(exc).__name__,
            completed_at=time.time(),
            retry_after=time.time() + UPDATE_COOLDOWN_SECONDS,
            elapsed_seconds=round(time.time() - started, 2),
        )


def start_background_health_check() -> None:
    """Start one coalesced startup check without making network YouTube calls."""

    global _health_check_started_for
    scope = str(state_root())
    with _health_check_lock:
        if _health_check_started_for == scope:
            return
        _health_check_started_for = scope

    activate_pending_runtime()

    def check() -> None:
        try:
            refresh_local_health_check()
            manifest = active_manifest()
            latest = latest_versions()
            update_job = update_state()
            if manifest and not pending_manifest() and not (
                update_job.get("status") == "running"
                or (update_job.get("status") == "ready" and update_job.get("phase") == "restart_required")
            ):
                current_provider = manifest.get("provider_version")
                provider_update = _is_newer(latest.get("provider_version"), current_provider)
                yt_update = _is_newer(latest.get("yt_dlp_version"), manifest.get("yt_dlp_version"))
                if provider_update and not _same_provider_major(latest.get("provider_version"), current_provider):
                    _update_state(
                        status="ready",
                        phase="major_update_requires_consent",
                        major_update_available=latest.get("provider_version"),
                    )
                elif provider_update or yt_update:
                    start_update_job(reason="update")
        except Exception as exc:
            # Health reporting is best-effort. A read-only or unavailable
            # SONEX_HOME must never surface as an unhandled daemon-thread
            # exception in the application or its tests.
            with contextlib.suppress(Exception):
                _update_state(last_health_check_at=time.time(), health_error=type(exc).__name__)

    thread = threading.Thread(target=check, name="sonex-youtube-health", daemon=True)
    thread.start()


def refresh_local_health_check() -> dict[str, Any]:
    """Run only local checks; never performs a remote version or YouTube request."""
    previous_state = _read_json(_state_path("state.json")) or {}
    manifest = active_manifest()
    if manifest:
        local_check = local_runtime_check(manifest)
        status = "ready" if local_check.get("healthy") else "degraded"
    else:
        local_check = {"healthy": False, "reason": "setup_required"}
        status = "setup_required"
    if previous_state.get("rollback_pending"):
        status = "degraded"
    return _update_state(last_health_check_at=time.time(), status=status, local_check=local_check)


def consume_restart_notice() -> str | None:
    """Consume a single update-ready notice for the current process/session."""

    state = update_state()
    if state.get("phase") != "restart_required" or not state.get("restart_required"):
        return None
    notice = f"YouTube runtime update ready · {state.get('previous_yt_dlp_version') or 'setup'} → {state.get('candidate_yt_dlp_version') or 'new'}\nRestart Sonex to apply."
    # Keep the persisted state useful for status while deduplicating notices per
    # process.  A process-local marker is enough because each TUI/API launch is
    # one application session.
    if getattr(consume_restart_notice, "_consumed", False):
        return None
    setattr(consume_restart_notice, "_consumed", True)
    return notice


def _main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--provider-monitor":
        if len(sys.argv) != 5:
            return 2
        return _provider_monitor(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    if len(sys.argv) >= 2 and sys.argv[1] == "--update-worker":
        _perform_update()
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised by detached workers
    raise SystemExit(_main())
