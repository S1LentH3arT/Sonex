"""Restricted Codex App Server transport for ChatGPT subscription access."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.llm.config import ProviderConfig
from src.llm.transport.base import (
    ChatResponse,
    LLMTransportError,
    ProviderRequest,
    ToolCall,
    Usage,
)
from src.log import sonex_home

CODEX_RUNTIME_VERSION = "0.146.0"
_FORBIDDEN_ITEM_TYPES = {
    "commandExecution",
    "fileChange",
    "mcpToolCall",
    "webSearch",
    "collabToolCall",
    "imageView",
    "dynamicToolCall",
}


def codex_home() -> Path:
    """Return Sonex's isolated Codex state directory."""
    return sonex_home() / "codex"


def bundled_codex_bin() -> Path:
    """Return the Codex binary managed by the Sonex CLI package."""
    executable = "codex.cmd" if os.name == "nt" else "codex"
    return Path(__file__).resolve().parents[2] / "cli-ui" / "node_modules" / ".bin" / executable


def resolve_codex_bin() -> Path:
    """Resolve only a Sonex-managed binary or an explicitly configured override."""
    override = os.getenv("SONEX_CODEX_BIN")
    path = Path(override).expanduser() if override else bundled_codex_bin()
    if not path.is_file():
        raise LLMTransportError(
            "OpenAI ChatGPT Subscription is unavailable because the Sonex Codex runtime is not installed."
        )
    return path


def validate_codex_runtime(path: Path | None = None) -> str:
    """Validate the pinned App Server runtime before trusting an override."""
    binary = path or resolve_codex_bin()
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LLMTransportError(f"Could not validate the Sonex Codex runtime: {exc}") from exc
    version = result.stdout.strip()
    if version != f"codex-cli {CODEX_RUNTIME_VERSION}":
        raise LLMTransportError(
            f"Incompatible Sonex Codex runtime '{version or 'unknown'}'; expected codex-cli {CODEX_RUNTIME_VERSION}."
        )
    return version


@lru_cache(maxsize=1)
def codex_app_server_status() -> tuple[bool, str | None]:
    """Return whether the managed App Server runtime is ready."""
    try:
        binary = resolve_codex_bin()
        if os.getenv("SONEX_CODEX_BIN"):
            return True, None
        package_path = binary.parents[1] / "@openai" / "codex" / "package.json"
        with package_path.open("r", encoding="utf-8") as stream:
            package = json.load(stream)
        if str(package.get("version") or "") != CODEX_RUNTIME_VERSION:
            raise LLMTransportError(
                f"Incompatible Sonex Codex package; expected {CODEX_RUNTIME_VERSION}."
            )
    except Exception as exc:
        return False, str(exc)
    return True, None


class CodexAppServer:
    """Small synchronous JSONL client with fail-closed server request handling."""

    def __init__(self, *, timeout: float = 120.0) -> None:
        self.timeout = timeout
        self._next_id = 1
        self._notifications: list[dict[str, Any]] = []
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="sonex-codex-")
        empty_cwd = Path(self._temporary_directory.name)
        state_home = codex_home()
        state_home.mkdir(parents=True, exist_ok=True)
        _write_restricted_config(state_home / "config.toml")
        binary = resolve_codex_bin()
        validate_codex_runtime(binary)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(state_home)
        environment["CODEX_SQLITE_HOME"] = str(state_home)
        self.process = subprocess.Popen(
            [str(binary), "app-server", "--listen", "stdio://", "--strict-config"],
            cwd=empty_cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(
            target=self._reader_loop,
            name="sonex-codex-app-server-reader",
            daemon=True,
        )
        self._reader.start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "sonex",
                    "title": "Sonex",
                    "version": "1.0.0",
                },
            },
        )
        self.notify("initialized", {})

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise LLMTransportError("Sonex Codex App Server stopped unexpectedly.")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _reader_loop(self) -> None:
        if self.process.stdout is None:
            self._lines.put(None)
            return
        for line in self.process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _read(self, timeout: float) -> dict[str, Any]:
        if self.process.stdout is None:
            raise LLMTransportError("Sonex Codex App Server stdout is unavailable.")
        try:
            line = self._lines.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            raise LLMTransportError("Sonex Codex App Server protocol read timed out.") from exc
        if not line:
            raise LLMTransportError("Sonex Codex App Server closed the protocol stream.")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LLMTransportError("Sonex Codex App Server returned invalid JSON.") from exc
        if not isinstance(message, dict):
            raise LLMTransportError("Sonex Codex App Server returned an invalid protocol message.")
        return message

    def _reject_server_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id is None:
            return
        self._send(
            {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": "Sonex rejects unregistered App Server requests.",
                },
            }
        )

    def _guard_notification(self, message: dict[str, Any]) -> None:
        params = message.get("params") or {}
        item = params.get("item") or {}
        item_type = item.get("type") if isinstance(item, dict) else None
        if item_type in _FORBIDDEN_ITEM_TYPES:
            if self.process.poll() is None:
                self.process.terminate()
            raise LLMTransportError(
                f"Codex App Server attempted forbidden item type '{item_type}'."
            )

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._send({"method": method, "id": request_id, "params": params or {}})
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                message = self._read(deadline - time.monotonic())
                if message.get("id") == request_id:
                    if message.get("error"):
                        error = message["error"]
                        detail = error.get("message") if isinstance(error, dict) else str(error)
                        raise LLMTransportError(f"Codex App Server {method} failed: {detail}")
                    result = message.get("result")
                    return result if isinstance(result, dict) else {}
                if "id" in message and "method" in message:
                    self._reject_server_request(message)
                elif "method" in message:
                    self._guard_notification(message)
                    self._notifications.append(message)
            raise LLMTransportError(f"Codex App Server {method} timed out.")

    def wait_for_notification(
        self,
        method: str,
        *,
        predicate: Any = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            for index, message in enumerate(self._notifications):
                if message.get("method") == method and (predicate is None or predicate(message)):
                    return self._notifications.pop(index)
            message = self._read(deadline - time.monotonic())
            if "id" in message and "method" in message:
                self._reject_server_request(message)
                continue
            self._guard_notification(message)
            if message.get("method") == method and (predicate is None or predicate(message)):
                return message
            if message.get("method"):
                self._notifications.append(message)
        raise LLMTransportError(f"Codex App Server notification {method} timed out.")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self._reader.join(timeout=1)
        self._temporary_directory.cleanup()

    def __enter__(self) -> "CodexAppServer":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _write_restricted_config(path: Path) -> None:
    """Create a deterministic configuration without inherited tools or integrations."""
    content = """approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
agents.enabled = false

[features]
apps = false
multi_agent = false
memories = false
hooks = false
"""
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


def start_chatgpt_device_login(server: CodexAppServer) -> dict[str, str]:
    """Start the official App Server managed device-code flow."""
    result = server.request("account/login/start", {"type": "chatgptDeviceCode"})
    required = ("loginId", "verificationUrl", "userCode")
    if result.get("type") != "chatgptDeviceCode" or any(not result.get(key) for key in required):
        raise LLMTransportError("Codex App Server did not return a valid device-code login.")
    return {key: str(result[key]) for key in required}


def wait_for_chatgpt_login(server: CodexAppServer, login_id: str) -> None:
    """Wait for a specific managed login and validate the resulting account."""
    event = server.wait_for_notification(
        "account/login/completed",
        predicate=lambda item: (item.get("params") or {}).get("loginId") == login_id,
    )
    params = event.get("params") or {}
    if not params.get("success"):
        raise LLMTransportError(str(params.get("error") or "ChatGPT sign-in failed."))
    account = server.request("account/read", {"refreshToken": True}).get("account")
    if not isinstance(account, dict) or account.get("type") != "chatgpt":
        raise LLMTransportError("Codex App Server did not activate a ChatGPT account.")


def logout_chatgpt_subscription() -> None:
    """Delete only Sonex's isolated managed ChatGPT session."""
    try:
        with CodexAppServer(timeout=30) as server:
            server.request("account/logout")
        return
    except Exception:
        auth_path = codex_home() / "auth.json"
        if not auth_path.exists():
            raise
        auth_path.unlink()


class CodexAppServerTransport:
    """Convert Sonex planning requests to a restricted structured Codex turn."""

    def send(self, request: ProviderRequest, config: ProviderConfig) -> dict[str, Any]:
        timeout = config.timeout or 120.0
        with CodexAppServer(timeout=timeout) as server:
            account = server.request("account/read", {"refreshToken": True}).get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                raise LLMTransportError("Open /login and connect OpenAI ChatGPT Subscription.")
            thread = server.request(
                "thread/start",
                {
                    "model": request.model,
                    "cwd": server._temporary_directory.name,
                    "approvalPolicy": "never",
                    "sandbox": "readOnly",
                    "serviceName": "sonex",
                },
            ).get("thread")
            if not isinstance(thread, dict) or not thread.get("id"):
                raise LLMTransportError("Codex App Server did not start a planning thread.")
            thread_id = str(thread["id"])
            try:
                output_text, usage = self._run_turn(server, thread_id, request)
            finally:
                try:
                    server.request("thread/delete", {"threadId": thread_id})
                except Exception:
                    pass
        return _structured_output_to_openai(output_text, request, usage)

    def _run_turn(
        self,
        server: CodexAppServer,
        thread_id: str,
        request: ProviderRequest,
    ) -> tuple[str, Usage]:
        tools = request.payload.get("tools") or []
        tool_names = [
            str((tool.get("function") or {}).get("name"))
            for tool in tools
            if isinstance(tool, dict) and (tool.get("function") or {}).get("name")
        ]
        schema = _planner_output_schema(tool_names)
        prompt = _planning_prompt(request.payload.get("messages") or [], tools)
        result = server.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "approvalPolicy": "never",
                "sandboxPolicy": {
                    "type": "readOnly",
                    "access": {
                        "type": "restricted",
                        "includePlatformDefaults": True,
                        "readableRoots": [],
                    },
                },
                "outputSchema": schema,
            },
        )
        turn = result.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise LLMTransportError("Codex App Server did not start a planning turn.")
        output = ""
        usage = Usage()
        while True:
            event = server.wait_for_notification(
                "turn/completed",
                predicate=lambda item: str(((item.get("params") or {}).get("turn") or {}).get("id") or "")
                == turn_id,
            )
            for queued in list(server._notifications):
                params = queued.get("params") or {}
                item = params.get("item") or {}
                item_type = item.get("type")
                if queued.get("method") == "item/completed" and item_type == "agentMessage":
                    output = str(item.get("text") or output)
                if queued.get("method") == "thread/tokenUsage/updated":
                    token_usage = params.get("tokenUsage") or params.get("usage") or {}
                    total = token_usage.get("total") or token_usage.get("totalTokens") or {}
                    if isinstance(total, dict):
                        usage.prompt_tokens = int(total.get("inputTokens") or 0)
                        usage.completion_tokens = int(total.get("outputTokens") or 0)
                        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
            completed_turn = (event.get("params") or {}).get("turn") or {}
            if completed_turn.get("status") != "completed":
                error = completed_turn.get("error") or {}
                raise LLMTransportError(str(error.get("message") or "Codex planning turn failed."))
            break
        if not output:
            raise LLMTransportError("Codex planning turn returned no structured output.")
        return output, usage


def _planning_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
    sections = [
        "You are the restricted planning model for Sonex. Do not inspect files, run commands, "
        "browse the web, call integrations, or use any built-in tool. Return only the JSON object "
        "required by the output schema. Sonex will validate and execute registered tools.",
    ]
    for message in messages:
        role = str(message.get("role") or "user").upper()
        sections.append(f"[{role}]\n{message.get('content') or ''}")
    sections.append(f"[REGISTERED_SONEX_TOOLS]\n{json.dumps(tools, ensure_ascii=False)}")
    return "\n\n".join(sections)


def _planner_output_schema(tool_names: list[str]) -> dict[str, Any]:
    name_schema: dict[str, Any] = {"type": "string"}
    if tool_names:
        name_schema["enum"] = tool_names
    return {
        "type": "object",
        "properties": {
            "output_text": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": ["string", "null"]},
                        "name": name_schema,
                        "arguments": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["id", "name", "arguments"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["output_text", "tool_calls"],
        "additionalProperties": False,
    }


def _structured_output_to_openai(
    output: str,
    request: ProviderRequest,
    usage: Usage,
) -> dict[str, Any]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LLMTransportError("Codex planning output did not match the required JSON schema.") from exc
    if not isinstance(parsed, dict):
        raise LLMTransportError("Codex planning output was not a JSON object.")
    allowed = {
        str((tool.get("function") or {}).get("name"))
        for tool in (request.payload.get("tools") or [])
        if isinstance(tool, dict)
    }
    normalized_calls = []
    for item in parsed.get("tool_calls") or []:
        if not isinstance(item, dict) or item.get("name") not in allowed:
            raise LLMTransportError("Codex planning output requested an unregistered Sonex tool.")
        normalized_calls.append(
            {
                "id": item.get("id"),
                "type": "function",
                "function": {
                    "name": item["name"],
                    "arguments": json.dumps(item.get("arguments") or {}),
                },
            }
        )
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": str(parsed.get("output_text") or ""),
                    "tool_calls": normalized_calls,
                },
                "finish_reason": "tool_calls" if normalized_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }
