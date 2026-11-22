"""One model call for the live desk.

gpt-4o-mini through the OpenAI client is the default. A Claude model is used
only when ANTHROPIC_API_KEY is set and the configured model name is a Claude
model. Any other name fails before a client is built. Set the name with
KHURSHEED_MODEL. A blank value keeps gpt-4o-mini.
"""

from __future__ import annotations

import contextvars
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import Iterator


DEFAULT_MODEL = "gpt-4o-mini"
MODEL_ENV = "KHURSHEED_MODEL"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_CLAUDE_MAX_TOKENS = 4096


class ModelSelectionError(ValueError):
    """The desk will not call this model, and it has not contacted a provider."""


@dataclass(frozen=True)
class ModelReply:
    """Text plus the usage the provider reported."""

    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str
    function_call: Any = None


class _ToolCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


def configured_model() -> str:
    """Model name for this process. Unset or blank stays on gpt-4o-mini."""
    return os.getenv(MODEL_ENV, "").strip() or DEFAULT_MODEL


def provider_for(model: str | None = None) -> str:
    """Return 'openai' or 'anthropic'. Raise ModelSelectionError otherwise."""
    name = _resolve(model)
    if name == DEFAULT_MODEL:
        return "openai"
    if _is_claude(name):
        if not os.getenv("ANTHROPIC_API_KEY", "").strip():
            raise ModelSelectionError(
                f"{name} is a Claude model and needs ANTHROPIC_API_KEY. Nothing was sent."
            )
        return "anthropic"
    raise ModelSelectionError(
        f"{name} is not available. This desk calls {DEFAULT_MODEL}, "
        "or a Claude model when ANTHROPIC_API_KEY is set. Nothing was sent."
    )


def refusal(model: str | None = None) -> str | None:
    """The selection error, or None when this name is allowed.

    A missing OpenAI key does not refuse gpt-4o-mini. Callers that can work
    without a model still decide that for themselves.
    """
    try:
        provider_for(model)
    except ModelSelectionError as exc:
        return str(exc)
    return None


def model_ready(model: str | None = None) -> bool:
    """True when the selected provider can be called with the key it needs."""
    try:
        provider = provider_for(model)
    except ModelSelectionError:
        return False
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    return True


def call_model(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    functions: list[dict[str, Any]] | None = None,
    function_call: str | None = None,
    client: Any = None,
) -> ModelReply:
    """Call the selected model and return its text and usage.

    ``client`` is the provider client for that selection. The chat agent passes
    its OpenAI client. Tests pass a fake. A refused name raises before either
    client is used. While a skill run is recording, the provider usage is added
    to that run. A call outside a skill run is not stored.
    """
    resolved = _resolve(model)
    provider = provider_for(resolved)
    if provider == "openai":
        active = client if client is not None else _openai_client()
        reply = _call_openai(
            active,
            resolved,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            functions=functions,
            function_call=function_call,
        )
    else:
        active = client if client is not None else _anthropic_client()
        reply = _call_anthropic(
            active,
            resolved,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            functions=functions,
            function_call=function_call,
        )
    _note_skill_usage(reply)
    return reply


def _resolve(model: str | None) -> str:
    if model is None:
        return configured_model()
    name = model.strip()
    return name or configured_model()


def _is_claude(name: str) -> bool:
    token = name.strip().lower()
    if "/" in token:
        token = token.rsplit("/", 1)[-1]
    return token.startswith("claude")


def _openai_client() -> Any:
    import openai

    return openai.OpenAI()


def _anthropic_client() -> Any:
    return _AnthropicHttp()


def _call_openai(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float | None,
    max_tokens: int | None,
    response_format: dict[str, Any] | None,
    functions: list[dict[str, Any]] | None,
    function_call: str | None,
) -> ModelReply:
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    if functions is not None:
        kwargs["functions"] = functions
    if function_call is not None:
        kwargs["function_call"] = function_call
    response = client.chat.completions.create(**kwargs)
    return _from_openai(response, model)


def _from_openai(response: Any, requested: str) -> ModelReply:
    choices = _field(response, "choices")
    message = None
    if isinstance(choices, list) and choices:
        message = _field(choices[0], "message")
    content = _field(message, "content") if message is not None else None
    prompt_tokens, completion_tokens = _usage_ints(
        _field(response, "usage"),
        "prompt_tokens",
        "completion_tokens",
    )
    return ModelReply(
        text=content if isinstance(content, str) else "",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=_reported_model(response, requested),
        function_call=_field(message, "function_call") if message is not None else None,
    )


def _call_anthropic(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float | None,
    max_tokens: int | None,
    response_format: dict[str, Any] | None,
    functions: list[dict[str, Any]] | None,
    function_call: str | None,
) -> ModelReply:
    system, converted, tools = _to_anthropic(messages, functions, response_format)
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens if max_tokens is not None else _CLAUDE_MAX_TOKENS,
        "messages": converted,
    }
    if system:
        payload["system"] = system
    if temperature is not None:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools
        if function_call == "auto":
            payload["tool_choice"] = {"type": "auto"}
        elif isinstance(function_call, str) and function_call not in {"", "none", "auto"}:
            payload["tool_choice"] = {"type": "tool", "name": function_call}
    response = client.messages.create(**payload)
    return _from_anthropic(response, model)


def _to_anthropic(
    messages: list[dict[str, Any]],
    functions: list[dict[str, Any]] | None,
    response_format: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    tool_ids: list[str] = []
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "system":
            content = message.get("content")
            if isinstance(content, str) and content:
                system_parts.append(content)
            continue
        if role == "function":
            tool_id = tool_ids.pop(0) if tool_ids else f"toolu_{index}"
            content = message.get("content")
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": content if isinstance(content, str) else json.dumps(content),
                }],
            })
            continue
        function = message.get("function_call")
        if role == "assistant" and function:
            name, arguments = _function_parts(function)
            tool_id = f"toolu_{index}"
            tool_ids.append(tool_id)
            blocks: list[dict[str, Any]] = []
            content = message.get("content")
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            blocks.append({
                "type": "tool_use",
                "id": tool_id,
                "name": name,
                "input": _object_arguments(arguments),
            })
            converted.append({"role": "assistant", "content": blocks})
            continue
        if role in {"user", "assistant"}:
            content = message.get("content")
            converted.append({
                "role": role,
                "content": content if isinstance(content, str) else "",
            })
    if response_format and response_format.get("type") == "json_object":
        system_parts.append("Return a single JSON object and no other text.")
    tools = _anthropic_tools(functions)
    return "\n\n".join(system_parts), converted, tools


def _anthropic_tools(functions: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not functions:
        return None
    tools = []
    for fn in functions:
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        tools.append({
            "name": name,
            "description": str(fn.get("description") or ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return tools or None


def _function_parts(function: Any) -> tuple[str, Any]:
    if isinstance(function, dict):
        return str(function.get("name") or ""), function.get("arguments")
    return str(getattr(function, "name", "") or ""), getattr(function, "arguments", None)


def _object_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _from_anthropic(response: Any, requested: str) -> ModelReply:
    blocks = _field(response, "content")
    parts: list[str] = []
    function_call = None
    if isinstance(blocks, list):
        for block in blocks:
            kind = str(_field(block, "type") or "")
            if kind == "text":
                text = _field(block, "text")
                if isinstance(text, str):
                    parts.append(text)
            elif kind == "tool_use" and function_call is None:
                raw_input = _field(block, "input")
                if not isinstance(raw_input, dict):
                    raw_input = {}
                function_call = _ToolCall(
                    str(_field(block, "name") or ""),
                    json.dumps(raw_input),
                )
    prompt_tokens, completion_tokens = _usage_ints(
        _field(response, "usage"),
        "input_tokens",
        "output_tokens",
    )
    return ModelReply(
        text="".join(parts),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=_reported_model(response, requested),
        function_call=function_call,
    )


class _AnthropicHttp:
    """Minimal Messages client. Built only after a Claude model is selected."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, **payload: Any) -> dict[str, Any]:
        import httpx

        key = os.environ["ANTHROPIC_API_KEY"].strip()
        try:
            response = httpx.post(
                _ANTHROPIC_URL,
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=120.0,
            )
        except httpx.TransportError:
            raise RuntimeError("Claude connection failed. Nothing was returned.") from None
        if response.status_code >= 400:
            raise RuntimeError(
                f"Claude request failed ({response.status_code}). Nothing was returned."
            )
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("Claude returned a response that was not JSON.") from None
        if not isinstance(data, dict):
            raise RuntimeError("Claude returned a response that was not JSON.")
        return data


def _field(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _reported_model(response: Any, requested: str) -> str:
    value = _field(response, "model")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return requested


def _usage_ints(usage: Any, prompt_key: str, completion_key: str) -> tuple[int | None, int | None]:
    if isinstance(usage, dict):
        return _as_int(usage.get(prompt_key)), _as_int(usage.get(completion_key))
    if usage is None:
        return None, None
    return _as_int(getattr(usage, prompt_key, None)), _as_int(getattr(usage, completion_key, None))


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class SkillRunUsage:
    """Token totals for the skill run that is executing on this thread."""

    def __init__(self) -> None:
        self.calls = 0
        self.model: str | None = None
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None

    def add(self, reply: ModelReply) -> None:
        self.calls += 1
        name = reply.model.strip() if isinstance(reply.model, str) else ""
        if name:
            seen = {part.strip() for part in (self.model or "").split(",") if part.strip()}
            if self.model is None:
                self.model = name
            elif name not in seen:
                self.model = f"{self.model}, {name}"
        if reply.prompt_tokens is not None:
            self.prompt_tokens = (self.prompt_tokens or 0) + reply.prompt_tokens
        if reply.completion_tokens is not None:
            self.completion_tokens = (self.completion_tokens or 0) + reply.completion_tokens

    def recorded(self) -> tuple[str | None, int | None, int | None]:
        """Columns for this run. A run that never called the model stays empty."""
        if self.calls == 0:
            return None, None, None
        return self.model, self.prompt_tokens, self.completion_tokens


_skill_usage: contextvars.ContextVar[tuple[SkillRunUsage, ...] | None] = contextvars.ContextVar(
    "skill_run_usage",
    default=None,
)


@contextmanager
def skill_run_usage() -> Iterator[SkillRunUsage]:
    """Collect call_model usage for one skill run. Nested runs keep their own totals."""
    usage = SkillRunUsage()
    current = _skill_usage.get()
    stack = () if current is None else current
    token = _skill_usage.set(stack + (usage,))
    try:
        yield usage
    finally:
        _skill_usage.reset(token)


def _note_skill_usage(reply: ModelReply) -> None:
    stack = _skill_usage.get()
    if not stack:
        return
    stack[-1].add(reply)
