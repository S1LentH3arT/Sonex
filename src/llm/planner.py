"""Planner support for language model configuration, catalogs, transports, and planning.

Implements the planner module responsibilities used by Sonex runtime flows.
Key public entry points include llm_plan.
"""

from __future__ import annotations

from src.api.builtin_commands import CommandIntent
from src.agent.action import Action, ToolAction
from src.llm.context_builder import build_planning_context
from src.llm.transport import ChatRequest
from src.thinking.config import ThinkingConfig
from src.tools.registry import ToolRegistry

PLANNER_SYSTEM_PROMPT = """You are Sonex, a Music Agent that manages music accounts and playback services.
Write like a restrained music curator and reliable playback operator. Lead with the result.
Do not use decorative emoji, canned assistant phrases, or mention being an AI.
Keep simple answers short. Use structure only when it improves a multi-item answer.
For visible formatting, use only: ## headings, **strong emphasis**, `inline highlights`,
ordered or '-' lists, fenced code blocks, and Markdown links. Do not emit raw HTML.
Use '-' for unordered list markers. Preserve emoji only when it is part of supplied music metadata.
The user-visible conversation history is separate from your model-only planning buffer.
Use only the compact planning buffer supplied in the user message.
The buffer is intentionally incomplete and short. Use Read for relevant context, user preferences, or memory.
Use Query for read-only provider data. Provider setup and authorization are user-driven through /extension; do not invent a connection tool call. Use Call for stable Sonex workflows.
Use Recommend exactly once for recommendation turns. Use Modify exactly once for an
explicit local playlist or up-next edit, batching every requested operation into that call.
Use Bash only when it is available and native shell or CLI behavior is actually useful.
When using Bash, submit reviewable commands through the commands array. Each item must be one simple command or one single-line pipeline.
Do not generate multiline scripts, shell control structures, functions, heredocs, eval, command substitution, subshells, or inline interpreter programs.
Split multi-step shell work into ordinary commands. Use at most one Bash tool call in a response and at most 12 commands in that call.
For playback requiring a user choice, call Call with workflow playback.select and wait for its structured result.
If tools are useful, call one or more tools with valid arguments. Tool calls execute serially in the order returned.
Do not place a tool call in the same response when its arguments depend on the result of an earlier call.
Otherwise answer the user directly.
Do not mention internal memory mechanics unless the user asks about them."""


def _format_command_intent(command_intent: CommandIntent | None) -> str:
    """Prepares format command intent for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs format command intent without duplicating the local rules.

    Example: _format_command_intent(command_intent=...) -> returns the value used by the surrounding Sonex flow.
    """
    if command_intent is None:
        return ""
    allowed = ", ".join(command_intent.allowed_tools) if command_intent.allowed_tools else "none"
    max_tool_calls = (
        str(command_intent.max_tool_calls)
        if command_intent.max_tool_calls is not None
        else "default"
    )
    return (
        "[command_intent]\n"
        f"command: {command_intent.command}\n"
        f"raw: {command_intent.raw}\n"
        f"args: {command_intent.args}\n"
        f"allowed_tools: {allowed}\n"
        f"max_tool_calls: {max_tool_calls}\n"
        f"guidance: {command_intent.intent_prompt}\n\n"
    )


def _planner_system_prompt(command_intent: CommandIntent | None) -> str:
    """Prepares planner system prompt for an internal Sonex flow.

    Typical use: Use this helper when nearby code needs planner system prompt without duplicating the local rules.

    Example: _planner_system_prompt(command_intent=...) -> returns the value used by the surrounding Sonex flow.
    """
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
    planning_feedback: str | None = None,
) -> Action:
    """Coordinates llm plan for the current Sonex flow.

    Typical use: Use this function when runtime code needs llm plan as part of a Sonex command, playback, auth, llm, or ui path.

    Example: llm_plan(user_input=..., tools=..., command_intent=...) -> returns the value used by the surrounding Sonex flow.
    """
    client = ThinkingConfig.get_client()
    model = ThinkingConfig.get_model()
    context = build_planning_context(user_input)
    allowed_tools = command_intent.allowed_tools if command_intent else None
    feedback_block = (
        f"[planning_feedback]\n{planning_feedback}\n\n"
        if planning_feedback
        else ""
    )

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
                    f"{feedback_block}"
                    f"[preloaded_memory]\n{context}"
                ),
            },
        ],
        tools=tools.agent_schemas(allowed_tools),
        tool_choice="auto",
    )
    response = client.generate(request)

    if response.tool_calls:
        first_call = response.tool_calls[0]
        return Action(
            tool=first_call.name,
            args=first_call.arguments,
            tool_calls=[
                ToolAction(
                    tool=tool_call.name,
                    args=tool_call.arguments,
                    call_id=tool_call.id,
                )
                for tool_call in response.tool_calls
            ],
            usage=response.usage.total_tokens,
        )

    return Action(output=response.output_text, usage=response.usage.total_tokens)
