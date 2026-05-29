from __future__ import annotations

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


def llm_plan(user_input: str, tools: ToolRegistry) -> Action:
    client = ThinkingConfig.get_client()
    model = ThinkingConfig.get_model()
    context = build_planning_context(user_input)

    request = ChatRequest(
        model=model,
        messages=[
            {
                "role": "system",
                "content": PLANNER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"[user_input]\n{user_input}\n\n"
                    f"[preloaded_memory]\n{context}"
                ),
            },
        ],
        tools=tools.schemas(),
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
