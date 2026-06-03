from typing import Any

from src.llm.adapter.base import DefaultAdapter, _coerce_text
from src.llm.transport.base import ChatRequest, ChatResponse, Usage, ToolCall


class GeminiAdapter(DefaultAdapter):
    """Adapter for Gemini or Google response protocol.

    Args:
        provider_name: name of the provider, defaults to 'gemini'.
    """
    provider_name = "gemini"

    def _build_native_payload(self, request: ChatRequest, resolved_model: str) -> dict[str, Any]:
        """Generate Google style response payload.

        Common payload schema:

        - **contents**: list of message contents with ``role`` and ``parts``.
        - **systemInstruction**: always system prompt for injection.
        - **generationConfig**: configuration options for generation, including ``temperature``, ``maxOutputTokens``, ``stopSequences`` and so on.
        - **tools**: with ``functionDeclarations`` as tool schema.
        """
        contents = []
        system_messages = []
        for message in request.messages:
            role = message.get("role")
            if role == "system":
                system_messages.append(_coerce_text(message.get("content")))
                continue
            contents.append(
                {
                    "role": _gemini_role(role),
                    "parts": _gemini_parts(message),
                }
            )

        native: dict[str, Any] = {
            "model": resolved_model,
            "contents": contents,
        }
        if system_messages:
            native["system_instruction"] = {
                "parts": [{"text": "\n\n".join(x for x in system_messages if x)}]
            }
        if request.tools:
            native["tools"] = [
                {
                    "function_declarations": [_gemini_tool(tool) for tool in request.tools],
                }
            ]
        if request.tool_choice is not None:
            native["tool_config"] = {"function_calling_config": _gemini_tool_choice(request.tool_choice)}
        if request.temperature is not None:
            native["generation_config"] = {"temperature": request.temperature}
        if request.max_tokens is not None:
            native.setdefault("generation_config", {})["max_output_tokens"] = request.max_tokens
        return native

    def _parse_native_response(self, data: dict[str, Any]) -> ChatResponse:
        """Parse Google style raw response and wrap as a unified format.

        Google style response schema:

        - **candidates**: includes ``content`` as response message and ``finishReason``.
        - **usageMetadata**: contains token data including ``promptTokenCount``, ``candidatesTokenCount`` and ``totalTokenCount``.

        Param ``parts`` in ``content`` contains ``text`` as message or ``functionCall`` as tool-call data.
        """
        usage_data = data.get("usageMetadata") or {}
        usage = Usage(
            prompt_tokens=int(usage_data.get("promptTokenCount") or 0),
            completion_tokens=int(usage_data.get("candidatesTokenCount") or 0),
            total_tokens=int(usage_data.get("totalTokenCount") or 0),
        )

        candidates = data.get("candidates") or []
        if not candidates:
            return ChatResponse(raw_output=data, usage=usage)

        first = candidates[0]
        parts = ((first.get("content") or {}).get("parts")) or []
        output_chunks = []
        tool_calls = []
        for part in parts:
            text = part.get("text")
            if text:
                output_chunks.append(text)
            function_call = part.get("functionCall") or {}
            if function_call.get("name"):
                tool_calls.append(
                    ToolCall(
                        id=function_call.get("id"),
                        name=function_call["name"],
                        arguments=function_call.get("args") or {},
                    )
                )

        return ChatResponse(
            output_text="\n".join(output_chunks).strip(),
            tool_calls=tool_calls,
            raw_output=data,
            usage=usage,
            finish_reason=first.get("finishReason"),
        )


def _gemini_role(role: str | None) -> str:
    """Message role in google style response.

    Only ``model`` and ``user``, tool calling is included in ``functionCall`` in ``parts`` of ``content``.
    """
    if role == "assistant":
        return "model"
    return "user"


def _gemini_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate Google style response message.

    In google style response, content parts include ``functionCall`` as tool-call and ``text`` as raw message.
    """
    if message.get("role") == "tool":
        return [
            {
                "functionResponse": {
                    "name": message.get("name") or "tool",
                    "response": {"content": _coerce_text(message.get("content"))},
                }
            }
        ]

    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                parts.append({"text": item.get("text", "")})
        if parts:
            return parts
    return [{"text": _coerce_text(content)}]


def _gemini_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Generate tool schema in google style response.

    Similar to OpenAI tool schema, ``functionDeclarations`` in ``tools`` includes param ``name``, ``description`` and ``parameters``.
    """
    function = tool.get("function") or {}
    parameters = function.get("parameters") or {"type": "object", "properties": {}}
    return {
        "name": function.get("name"),
        "description": function.get("description"),
        "parameters": parameters,
    }


def _gemini_tool_choice(choice: str | dict[str, Any]) -> dict[str, Any]:
    """Build tool choice in google style response.

    Default tool choice is ``auto``. Note that ``none`` means no tools provided with chat mode only.
    """
    if isinstance(choice, str):
        mapping = {
            "auto": {"mode": "AUTO"},
            "none": {"mode": "NONE"},
            "required": {"mode": "ANY"},
        }
        return mapping.get(choice, {"mode": "AUTO"})

    function = choice.get("function") or {}
    return {
        "mode": "ANY",
        "allowed_function_names": [function.get("name")],
    }
