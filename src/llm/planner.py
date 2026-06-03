from __future__ import annotations

from src.api.builtin_commands import CommandIntent
from src.agent.action import Action
from src.llm.context_builder import build_planning_context
from src.llm.transport import ChatRequest
from src.thinking.config import ThinkingConfig
from src.tools.registry import ToolRegistry

PLANNER_SYSTEM_PROMPT = """You are Sonex's planner.
The user-visible conversation history is separate from your model-only planning buffer.
Use only the compact planning buffer supplied in the user message.
The buffer is intentionally incomplete and short. If you need other stored facts, call search_memory or search_context.
search_context is cache-first by default and falls back to full structured context.
If a tool is useful, call exactly one tool with valid arguments. Otherwise answer the user directly.
Do not mention internal memory mechanics unless the user asks about them."""


def _format_command_intent(command_intent: CommandIntent | None) -> str:
    if command_intent is None:
        return ""
    allowed = ", ".join(command_intent.allowed_tools) if command_intent.allowed_tools else "any"
    return (
        "[command_intent]\n"
        f"command: {command_intent.command}\n"
        f"raw: {command_intent.raw}\n"
        f"args: {command_intent.args}\n"
        f"allowed_tools: {allowed}\n"
        f"guidance: {command_intent.intent_prompt}\n\n"
    )


def _planner_system_prompt(command_intent: CommandIntent | None) -> str:
    if command_intent is None or not command_intent.intent_prompt:
        return PLANNER_SYSTEM_PROMPT
    return (
        f"{PLANNER_SYSTEM_PROMPT}\n\n"
        "Command intent guidance:\n"
        f"{command_intent.intent_prompt}"
    )


def llm_plan(
    user_input: str,
    tools: ToolRegistry,
    command_intent: CommandIntent | None = None,
) -> Action:
    client = ThinkingConfig.get_client()
    model = ThinkingConfig.get_model()
    context = build_planning_context(user_input)
    allowed_tools = command_intent.allowed_tools if command_intent else None

    request = ChatRequest(
        model=model,
        messages=[
            {
                "role": "system",
                "content": _planner_system_prompt(command_intent),
            },
            {
                "role": "user",
                "content": (
                    f"{_format_command_intent(command_intent)}"
                    f"[user_input]\n{user_input}\n\n"
                    f"[preloaded_memory]\n{context}"
                ),
            },
        ],
        tools=tools.schemas(allowed_tools),
        tool_choice="auto",
    )
    response = client.generate(request)

    if response.tool_calls:
        tool_call = response.tool_calls[0]
        return Action(
            tool=tool_call.name,
            args=tool_call.arguments,
            usage=response.usage.total_tokens,
        )

    return Action(output=response.output_text, usage=response.usage.total_tokens)
