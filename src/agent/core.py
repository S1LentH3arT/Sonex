import json
from dataclasses import dataclass
from typing import Any

import tiktoken

from src.agent.action import Action
from src.agent.memory import MemoryStore
from src.config.thinking import ThinkingConfig
from src.llm.compact import snip_compact, auto_compact
from src.llm.planner import llm_plan
from src.tools.registry import ToolRegistry

MAX_TOKEN_LIMIT = 60000

@dataclass
class AgentState:
    """state type includes: status, tool, context, error
    status: agent is doing something, e.g. "compacting", "planning", "cleaning"
    tool: agent is calling a tool
    complete: agent has finished executing
    error: something went wrong
    confirm: current step requires confirmation
    """
    type: str = None

    tool: str = None
    args: dict = None
    result: Any = None
    content: str = ""
    tokens: int = 0
    is_error: bool = False

def _to_serializable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)
    return value

def _estimate_tokens(messages: list[dict]) -> int:
    try:
        enc = tiktoken.encoding_for_model("gpt-4o")
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    text = json.dumps(messages, ensure_ascii=False, default=str)
    return len(enc.encode(text))

def _format_error(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    if not lines:
        return exc.__class__.__name__
    return lines[0][:500]

"""agent_loop重写思路：
每轮开始，先压缩上下文
再执行llm_planner，让llm分析问题，是否需要调用工具
每轮结束时将工具调用结果追加到消息历史
如果不需要调用工具，那么退出loop
"""
from typing import Generator

def agent_loop(
    user_input: str,
    tools: ToolRegistry,
    memory_store: MemoryStore,
    session_id: str,
) -> Generator[AgentState, AgentState, None]:
    history: list[dict[str, Any]] = [{"role": "user", "content": user_input}]
    _total_tokens = 0

    # 对user_input做预处理，初始化信息写入plan.md文件
    model = ThinkingConfig.get_model()
    _total_tokens += memory_store.init_plan(user_input=user_input, model=model)

    while True:
        # 先压缩上下文
        if history:
            snip_compact(history)

        token_count: int = _estimate_tokens(history)
        if token_count > MAX_TOKEN_LIMIT:
            auto_compact(history, model, session_id)

        _total_tokens += memory_store.append_plan(model)

        yield AgentState(
            type="status",
            content="compacting",
            tokens=_total_tokens,
        )
        # 执行planner
        action = Action
        try:
            action = llm_plan(
                memory=memory_store,
            )
        except Exception as exc:
            error_text = _format_error(exc)
            message = f"Planning failed: {error_text}"
            history.append ({"kind": "planning error", "content": message})
            yield AgentState(
                type="error",
                content=error_text,
                is_error=True,
            )

        _total_tokens += action.usage

        yield AgentState(
            type="status",
            content="planning",
            tokens=_total_tokens,
        )

        # 如果llm执行结果中没有工具调用，则loop结束
        if action.tool is None:
            answer = action.output
            history.append ({"role": "assistant", "content": answer})
            yield AgentState(
                type="complete",
                content=answer,
            )
            return

        # 使用工具
        tool_func = tools.get(action.tool)
        if not tool_func:
            message = f"Tool '{action.tool}' not found or not allowed."
            history.append ({"kind": "tool error", "content": message})
            yield AgentState(
                type="error",
                content=message,
                is_error=True,
            )
            continue

        if tool_func.confirm_required:
            decision = yield AgentState(
                type="confirm",
                tool=action.tool,
                args=action.args,
            )
            if not decision:
                history.append ({"kind": "tool rejected", "content": f"{action.tool} was rejected"})
                continue

        tool_args = action.args or {}
        if not isinstance(tool_args, dict):
            message = "Planner returned invalid tool arguments."
            history.append ({"kind": "tool error", "content": message})
            yield AgentState(
                type="error",
                content=message,
                is_error=True,
            )
            continue

        yield AgentState(
            type="tool",
            tool=action.tool,
            args=tool_args,
            tokens=_total_tokens,
        )

        tool_result = Any
        try:
            res = tools.invoke(action.tool, tool_args)
            tool_result = _to_serializable(res)
        except Exception as exc:
            error_text = _format_error(exc)
            history.append({"tool": action.tool, "error": error_text})
            message = f"Tool execution failed: {error_text}"
            history.append ({"kind": "tool error", "content": message})
            yield AgentState(
                type="error",
                tool=action.tool,
                content=message,
                is_error=True,
            )

        yield AgentState(
            type="tool",
            tool=action.tool,
            result=tool_result,
        )

        _total_tokens += memory_store.append_findings(action.tool, tool_result, model)

        # 将工具结果追加到对话历史
        observation = {
            "tool": action.tool,
            "args": tool_args,
            "result": tool_result,
        }
        history.append(observation)

        _total_tokens += memory_store.append_process(action.tool, tool_args, tool_result, model)

        yield AgentState(
            type="status",
            content="cleaning",
            tokens=_total_tokens,
        )
