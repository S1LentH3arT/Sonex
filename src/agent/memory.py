import json
import subprocess
from dataclasses import dataclass
from datetime import timezone, datetime
from pathlib import Path
from typing import Any

from src.config.thinking import sonex_home, ThinkingConfig
from src.tools.registry import registry, Params

_INIT_PLANNING_SYSTEM_PROMPT = """You're a prompt optimizer, you need to analyze the user's prompt and extract the key information.
Then generate a clear and simple initial plan with consice words in strict markdown format.
Only generate the markdown symbol(#, -, * and so on) and text information, NO other extra words.
MUST BE ACCURATE OR THE FOLLOWING MODELS WILL BE MISLED AND PUZZLED!
"""

_PLAN_SYSTEM_PROMPT = """You're a workflow planner, you need to analyze and summarize the three files below to keep track of current stage.
You're required to decide whether the current task is handled, what's the next step to complete.
Then mark the current process and generate a clear summary with consice words in strict markdown format.
Only generate the markdown symbol(#, -, * and so on) and text information, NO other extra words.
"""

_FINDINGS_SYSTEM_PROMPT = """You're a result analyst, you need to analyze the tool call result and extract the key information.
Then generate a consice tool-call summary(example: what tool + what result) in strict markdown format.
Highlight what kind of tool-call succeeded and especially what kind of tool call failed. 
Only generate the markdown symbol(#, -, * and so on) and text information, NO other extra words.
"""

_PROCESS_SYSTEM_PROMPT = """You're a operation logger, you need to record what is done with accurate words.
Compared to the findings, you need to concentrate on the process, include enough details.
Make sure the process is clear and traceable and avoid redundant information.
Then generate a consice log(short in one line) with accurate words in strict markdown format.
Only generate the markdown symbol(#, -, * and so on) and text information, NO other extra words.
"""

@dataclass(frozen=True)
class SessionPaths:
    session_id: str
    plan: Path
    findings: Path
    process: Path

# 记忆仓库
class MemoryStore:
    def __init__(self):
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%SZ")
        self.paths = SessionPaths(
            session_id=session_id,
            plan=sonex_home() / "sessions" / session_id / "plan.md",
            findings=sonex_home() / "sessions" / session_id / "findings.md",
            process=sonex_home() / "sessions" / session_id / "process.md",
        )
        self._init_session()

    def _init_session(self) -> None:
        root = sonex_home() / "sessions" / self.paths.session_id
        root.mkdir(parents=True, exist_ok=True)
        if not self.paths.plan.exists():
            self.paths.plan.write_text("# Plan\n\n", encoding="utf-8")
        if not self.paths.findings.exists():
            self.paths.findings.write_text("# Findings\n\n", encoding="utf-8")
        if not self.paths.process.exists():
            self.paths.process.write_text("# Process\n\n", encoding="utf-8")

    # 读取当前记忆
    def load_memory(self) -> dict[str, str]:
        return {
            "plan": self.paths.plan.read_text(encoding="utf-8"),
            "findings": self.paths.findings.read_text(encoding="utf-8"),
            "process": self.paths.process.read_text(encoding="utf-8"),
        }

    # 对用户输入进行预处理
    def init_plan(self, user_input: str, model: str) -> int :
        client = ThinkingConfig.get_client()
        messages = [
            {
                "role": "system",
                "content": _INIT_PLANNING_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_input,
            }
        ]

        response = client.responses.create(
            model=model,
            messages=messages,
            max_tokens=2000,
        )
        text = response.output_text.strip()

        # 追加内容
        with self.paths.plan.open("a", encoding="utf-8") as f:
            f.write(text)

        usage = getattr(response, "usage", None)
        total_tokens = getattr(response, "total_tokens", 0) if usage else 0

        return total_tokens

    # 工具调用前更新plan.md
    def append_plan(self, model: str) -> int:
        client = ThinkingConfig.get_client()
        memory = self.load_memory()

        messages = [
            {
                "role": "system",
                "content": _PLAN_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": f"[plan.md]\n{memory["plan"][-2000:]}",
            },
            {
                "role": "user",
                "content": f"[plan.md]\n{memory["findings"][-2000:]}",
            },
            {
                "role": "user",
                "content": f"[plan.md]\n{memory["process"][-2000:]}",
            },
        ]
        response = client.responses.create(
            model=model,
            messages=messages,
            max_tokens=600,
        )
        text = response.output_text.strip()

        with self.paths.plan.open("a", encoding="utf-8") as f:
            f.write(text)

        usage = getattr(response, "usage", None)
        total_tokens = getattr(response, "total_tokens", 0) if usage else 0

        return total_tokens

    # 工具调用后更新findings.md
    def append_findings(self, tool: str, tool_result: Any, model: str) -> int:
        client = ThinkingConfig.get_client()
        payload = {
            "tool_name": tool,
            "tool_result": tool_result,
        }

        messages = [
            {
                "role": "system",
                "content": _FINDINGS_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Generate markdown only with no extra prose.\n"
                    "Input JSON:\n"
                    f"{json.dumps(payload, ensure_ascii=False, default=str)}"
                ),
            },
        ]
        response = client.responses.create(
            model=model,
            messages=messages,
            max_tokens=600,
        )
        text = response.output_text.strip()

        with self.paths.findings.open("a", encoding="utf-8") as f:
            f.write(text)

        usage = getattr(response, "usage", None)
        total_tokens = getattr(response, "total_tokens", 0) if usage else 0

        return total_tokens

    # 一轮结束前更新process.md
    def append_process(self, tool: str, args: dict, tool_result: Any, model: str) -> int:
        client = ThinkingConfig.get_client()
        payload = {
            "tool_name": tool,
            "tool_args": args,
            "tool_result": tool_result,
        }

        messages = [
            {
                "role": "system",
                "content": _PROCESS_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Generate markdown only with no extra prose.\n"
                    "Input JSON:\n"
                    f"{json.dumps(payload, ensure_ascii=False, default=str)}"
                ),
            },
        ]
        response = client.responses.create(
            model=model,
            messages=messages,
            max_tokens=100,
        )
        text = response.output_text.strip()

        with self.paths.process.open("a", encoding="utf-8") as f:
            f.write(text)

        usage = getattr(response, "usage", None)
        total_tokens = getattr(response, "total_tokens", 0) if usage else 0

        return total_tokens

# 搜索记忆
def search_memory(query: str, root: Path | None = None) -> list[dict[str, str]]:
    path = root or sonex_home() / "sessions"
    cmd = ["grep", "-RIn", "--include=*.md", query, str(path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "No matches found.")

    hits: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        # 分成三部分：路径、行号、内容
        parts = line.split(":", maxsplit=2)
        if len(parts) != 3:
            continue
        file_path, line_num, content = parts
        hits.append(
            {
                "file_path": file_path,
                "line_num": line_num,
                "content": content.strip(),
            }
        )
    return hits

# 搜索会话
def search_transcript(query: str, root: Path | None = None) -> list[dict[str, str]]:
    path = root or sonex_home() / "transcripts"
    cmd = ["grep", "-RIn", "--include=*.jsonl", query, str(path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "No matches found.")

    hits: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split(":", maxsplit=2)
        if len(parts) != 3:
            continue
        file_path, line_num, content = parts
        hits.append(
            {
                "file_path": file_path,
                "line_num": line_num,
                "content": content.strip(),
            }
        )
    return hits

registry.register(
    name="search_memory",
    type="meomry",
    description="Search memory markdown files in the specified directory.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The information or key words to search."},
            "root": {"type": "Path", "description": "The specific directory path of memory files."},
        },
        required=["query", "root"],
    ),
    fn=search_memory,
    enable=True
)

registry.register(
    name="search_transcript",
    type="memory",
    description="Search transcript jsonl files in the specified directory.",
    parameters=Params(
        type="object",
        properties={
            "query": {"type": "string", "description": "The information or key words to search."},
            "root": {"type": "Path", "description": "The specific directory path of transcript files."},
        },
        required=["query", "root"],
    ),
    fn=search_transcript,
    enable=True
)