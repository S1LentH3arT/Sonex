"""Anthropic adapter support for language model configuration, catalogs, transports, and planning.

Implements the anthropic_adapter module responsibilities used by Sonex runtime flows.
Key public entry points include AnthropicAdapter.
"""

from typing import Any

from src.llm.adapter.base import DefaultAdapter, _coerce_text
from src.llm.transport.base import ChatRequest, ChatResponse, Usage, ToolCall


class AnthropicAdapter(DefaultAdapter):
    """Adapter for parsing Anthropic style LLM API Calling.

    Args:
        provider_name: name of the provider, defaults to 'anthropic'.
    """
    provider_name = "anthropic"

    def _build_native_payload(self, request: ChatRequest, resolved_model: str) -> dict[str, Any]:
        """Generate payload for Anthropic style request.

        Common payload schema:

        - **model**: model for LLM calling.
        - **messages**: anthropic style message, including ``role`` and ``content``.
        - **system**: system instruction for prompt injection.
        - **tools**: description for available tools.
        - **tool_choice**: tool orchestration skills if instructed.
        - **max_tokens**: max token limit in a calling.
        - **temperature**: model internal parameter.
        """
        system_messages = []
        messages = []
        for message in request.messages:
            role = message.get("role")
            if role == "system":
                system_messages.append(_coerce_text(message.get("content")))
                continue
            messages.append(
                {
                    "role": role,
                    "content": _anthropic_content(message),
                }
            )

        native: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
        }
        if system_messages:
            native["system"] = "\n\n".join(x for x in system_messages if x)
        if request.tools:
            native["tools"] = [_anthropic_tool(tool) for tool in request.tools]
        if request.tool_choice is not None:
            native["tool_choice"] = _anthropic_tool_choice(request.tool_choice)
        if request.max_tokens is not None:
            native["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            native["temperature"] = request.temperature
        return native

    def _parse_native_response(self, data: dict[str, Any]) -> ChatResponse:
        """Extract params from a raw response and wrap as a unified response format.

        Anthropic style response combine text and tool calls in ``content`` param.
        Extract two parts from raw response and append to the corresponding list.
        """
        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_data.get("input_tokens") or 0),
            completion_tokens=int(usage_data.get("output_tokens") or 0),
            total_tokens=int(
                (usage_data.get("input_tokens") or 0) + (usage_data.get("output_tokens") or 0)
            ),
        )

        output_chunks = []
        tool_calls = []
        for block in data.get("content") or []:
            block_type = block.get("type")
            if block_type == "text" and block.get("text"):
                output_chunks.append(block["text"])
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id"),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )

        return ChatResponse(
            output_text="\n".join(output_chunks).strip(),
            tool_calls=tool_calls,
            raw_output=data,
            usage=usage,
            finish_reason=data.get("stop_reason"),
        )

def _anthropic_content(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse Anthropic style response content.

    Anthropic style response content includes ``role`` and ``content`` params.
    Content for ``tool`` contains tool-call results and tool-call id. Content
    for other roles like ``user`` and ``assistant`` only contains raw text .
    """
    if message.get("role") == "tool":
        return [
            {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id"),
                "content": _coerce_text(message.get("content")),
            }
        ]

    content = message.get("content")
    if isinstance(content, list):
        blocks = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                blocks.append({"type": "text", "text": item.get("text", "")})
        if blocks:
            return blocks
    return [{"type": "text", "text": _coerce_text(content)}]


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Return Anthropic style tool schema.

    - **name**: The name of the tool.
    - **description**: A brief description of the tool's function.
    - **input_schema**: The input schema of the tool, includes ``type`` and ``properties``.
    """
    function = tool.get("function") or {}
    return {
        "name": function.get("name"),
        "description": function.get("description"),
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def _anthropic_tool_choice(choice: str | dict[str, Any]) -> dict[str, Any]:
    """Return Anthropic style tool choice.

    Default tool choice is ``auto``. **"required"** means the model must use a tool.
    """
    if isinstance(choice, str):
        mapping = {
            "auto": {"type": "auto"},
            # Default tool_choice is auto
            "none": {"type": "auto"},
            "required": {"type": "any"},
        }
        return mapping.get(choice, {"type": "auto"})

    function = choice.get("function") or {}
    return {
        "type": "tool",
        "name": function.get("name"),
    }
