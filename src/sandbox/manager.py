"""Bubblewrap-backed execution for the native Agent Bash tool."""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from src.log import sonex_home
from src.sandbox.guardrail import GuardrailDecision, inspect_script
from src.workspace import user_music_dir

DEFAULT_TIMEOUT_MS = 30_000
MAX_TIMEOUT_MS = 120_000
MAX_OUTPUT_BYTES = 64 * 1024
AUDIT_RETENTION_SECONDS = 7 * 24 * 60 * 60


class SandboxState(str, Enum):
    READY = "ready"
    UNCONFIGURED = "unconfigured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SandboxReport:
    state: SandboxState
    message: str
    missing: tuple[str, ...] = ()
    work_dir: str | None = None


@dataclass(frozen=True, slots=True)
class BashExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    policy: str
    audit_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_cwd(value: str) -> str:
    requested = PurePosixPath(str(value or "/work"))
    if not requested.is_absolute() or ".." in requested.parts:
        raise ValueError("cwd must be an absolute sandbox path.")
    if requested == PurePosixPath("/work") or requested.is_relative_to(PurePosixPath("/work")):
        return str(requested)
    if requested == PurePosixPath("/music") or requested.is_relative_to(PurePosixPath("/music")):
        return str(requested)
    if requested == PurePosixPath("/tmp") or requested.is_relative_to(PurePosixPath("/tmp")):
        return str(requested)
    raise ValueError("cwd must be within /work, /music, or /tmp.")


class SandboxManager:
    """Own sandbox readiness, Sonex directories, execution, and audit records."""

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or sonex_home() / "sandbox"
        self.work_dir = self.root / "work"
        self.audit_dir = self.root / "audit"
        self._cached_report: tuple[float, SandboxReport] | None = None

    def status(self, *, refresh: bool = False) -> SandboxReport:
        if not refresh and self._cached_report and time.monotonic() - self._cached_report[0] < 5:
            return self._cached_report[1]
        missing: list[str] = []
        if platform.system() != "Linux":
            missing.append("Linux or WSL2")
        if shutil.which("bwrap") is None:
            missing.append("bubblewrap")
        if missing:
            report = SandboxReport(
                SandboxState.UNAVAILABLE,
                "Sandbox is unavailable.",
                tuple(missing),
            )
        elif not self.work_dir.is_dir() or not self.audit_dir.is_dir():
            report = SandboxReport(
                SandboxState.UNCONFIGURED,
                "Sandbox resources are not configured.",
                work_dir=str(self.work_dir),
            )
        else:
            probe_error = self._probe()
            if probe_error:
                report = SandboxReport(
                    SandboxState.UNAVAILABLE,
                    "Sandbox is unavailable.",
                    (probe_error,),
                    str(self.work_dir),
                )
            else:
                report = SandboxReport(
                    SandboxState.READY,
                    "Sandbox is ready.",
                    work_dir=str(self.work_dir),
                )
        self._cached_report = (time.monotonic(), report)
        return report

    def configure(self) -> SandboxReport:
        if platform.system() != "Linux" or shutil.which("bwrap") is None:
            return self.status(refresh=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        os.chmod(self.work_dir, 0o700)
        os.chmod(self.audit_dir, 0o700)
        self._prune_audits()
        return self.status(refresh=True)

    def ready(self) -> bool:
        return self.status().state == SandboxState.READY

    def execute(
        self,
        script: str,
        *,
        cwd: str = "/work",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> BashExecutionResult:
        audit_id = uuid.uuid4().hex
        started = time.monotonic()
        decision = inspect_script(script)
        safe_cwd: str
        try:
            safe_cwd = _safe_cwd(cwd)
            bounded_timeout = min(MAX_TIMEOUT_MS, max(1_000, int(timeout_ms)))
        except (TypeError, ValueError) as exc:
            result = BashExecutionResult(
                exit_code=None,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                truncated=False,
                policy="denied",
                audit_id=audit_id,
            )
            self._write_audit(audit_id, decision, result, started)
            return result
        if not decision.allowed:
            result = BashExecutionResult(
                exit_code=None,
                stdout="",
                stderr="Command denied by the Sonex Bash guardrail.",
                timed_out=False,
                truncated=False,
                policy="denied",
                audit_id=audit_id,
            )
            self._write_audit(audit_id, decision, result, started)
            return result
        report = self.status()
        if report.state != SandboxState.READY:
            result = BashExecutionResult(
                exit_code=None,
                stdout="",
                stderr="Sandbox is not ready. Run /sandbox.",
                timed_out=False,
                truncated=False,
                policy="sandbox_unavailable",
                audit_id=audit_id,
            )
            self._write_audit(audit_id, decision, result, started)
            return result

        command = self._command(script, safe_cwd)
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True,
        )
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        stdout_state = {"truncated": False}
        stderr_state = {"truncated": False}
        stdout_thread = threading.Thread(
            target=self._drain_pipe,
            args=(process.stdout, stdout_buffer, stdout_state),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._drain_pipe,
            args=(process.stderr, stderr_buffer, stderr_state),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        timed_out = False
        try:
            process.wait(timeout=bounded_timeout / 1000)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout_thread.join()
        stderr_thread.join()
        stdout = self._decode_output(bytes(stdout_buffer), stdout_state["truncated"])
        stderr = self._decode_output(bytes(stderr_buffer), stderr_state["truncated"])
        result = BashExecutionResult(
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            truncated=stdout_state["truncated"] or stderr_state["truncated"],
            policy="allowed",
            audit_id=audit_id,
        )
        self._write_audit(audit_id, decision, result, started)
        return result

    def _probe(self) -> str | None:
        command = self._base_command()
        command.extend(("--chdir", "/work", "--", "/bin/bash", "--noprofile", "--norc", "-c", "exit 0"))
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=3,
                check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return str(exc)
        if completed.returncode == 0:
            return None
        detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return detail[-1][:240] if detail else "Bubblewrap probe failed."

    def _base_command(self) -> list[str]:
        command = [
            shutil.which("bwrap") or "bwrap",
            "--unshare-all",
            "--share-net",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "HOME",
            "/work",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--ro-bind",
            "/usr",
            "/usr",
        ]
        for host_path in ("/bin", "/lib", "/lib64"):
            if Path(host_path).exists():
                command.extend(("--ro-bind", host_path, host_path))
        command.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"))
        command.extend(("--bind", str(self.work_dir), "/work"))
        try:
            music_dir = user_music_dir()
        except Exception:
            music_dir = Path("/__sonex_missing_music__")
        if music_dir.is_dir():
            command.extend(("--ro-bind", str(music_dir), "/music"))
        else:
            command.extend(("--dir", "/music"))
        return command

    def _command(self, script: str, cwd: str) -> list[str]:
        command = self._base_command()
        command.extend(
            (
                "--chdir",
                cwd,
                "--",
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                script,
            )
        )
        return command

    @staticmethod
    def _drain_pipe(
        stream: Any,
        buffer: bytearray,
        state: dict[str, bool],
    ) -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                remaining = MAX_OUTPUT_BYTES - len(buffer)
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    state["truncated"] = True
        finally:
            stream.close()

    @staticmethod
    def _decode_output(value: bytes, truncated: bool) -> str:
        text = value.decode("utf-8", errors="replace")
        if truncated:
            text += "\n[output truncated]"
        return text

    def _write_audit(
        self,
        audit_id: str,
        decision: GuardrailDecision,
        result: BashExecutionResult,
        started: float,
    ) -> None:
        try:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.audit_dir, 0o700)
            path = self.audit_dir / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
            payload = {
                "audit_id": audit_id,
                "timestamp": time.time(),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "script_sha256": decision.script_sha256,
                "script_length": decision.script_length,
                "command_shape": list(decision.command_shape),
                "guardrail_rules": list(decision.rule_ids),
                "policy": result.policy,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "truncated": result.truncated,
            }
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
            os.chmod(path, 0o600)
            self._prune_audits()
        except OSError:
            return

    def _prune_audits(self) -> None:
        cutoff = time.time() - AUDIT_RETENTION_SECONDS
        try:
            candidates = tuple(self.audit_dir.glob("*.jsonl"))
        except OSError:
            return
        for path in candidates:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
