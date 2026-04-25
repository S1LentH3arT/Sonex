import json
import os
from datetime import time
from pathlib import Path
from typing import Any

COMPACT_SYSTEM_PROMPR = ""

MAX_TOKEN_LIMIT = 3000

def _default_transcript_path() -> Path:
    custom = os.environ.get("TRANSCRIPT_PATH")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".sonex" / "transcripts"

def input_compact(user_input: str) -> str:

# 当token超过阈值时，保存完整对话到磁盘并让llm做摘要
def auto_compact(history: list) -> list:
    # 保存完整对话
    transcript_path = _default_transcript_path() / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w", encoding="utf-8") as f:
        for msg in history:
            f.write(json.dumps(msg, default=str) + "\n")

    # 让llm做摘要
    