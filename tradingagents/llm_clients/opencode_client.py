import json
import subprocess
import uuid
from typing import Any, Iterable, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from .base_client import BaseLLMClient


_DEFAULT_OPENCODE_COMMAND = ("opencode", "run")


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_first_json_value(text: str) -> str:
    candidate = _strip_code_fences(text)
    decoder = json.JSONDecoder()

    for index, char in enumerate(candidate):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(candidate[index:])
            return candidate[index:index + end]
        except json.JSONDecodeError:
            continue

    raise ValueError("OpenCode output did not contain valid JSON")


def _schema_json(schema: type) -> str:
    if hasattr(schema, "model_json_schema"):
        return json.dumps(schema.model_json_schema(), indent=2, sort_keys=True)
    if hasattr(schema, "schema"):
        return json.dumps(schema.schema(), indent=2, sort_keys=True)
    raise TypeError(f"Unsupported schema type: {schema!r}")


def _validate_structured_output(schema: type, payload: str) -> Any:
    if hasattr(schema, "model_validate_json"):
        return schema.model_validate_json(payload)
    if hasattr(schema, "parse_raw"):
        return schema.parse_raw(payload)
    raise TypeError(f"Unsupported schema type: {schema!r}")


def _tool_schema(tool: Any) -> dict[str, Any]:
    if hasattr(tool, "args_schema") and tool.args_schema is not None:
        return json.loads(_schema_json(tool.args_schema))
    if hasattr(tool, "tool_call_schema") and tool.tool_call_schema is not None:
        return json.loads(_schema_json(tool.tool_call_schema))
    if hasattr(tool, "args") and isinstance(tool.args, dict):
        return {"type": "object", "properties": tool.args}
    return {"type": "object", "properties": {}}


def _tool_spec(tool: Any) -> dict[str, Any]:
    return {
        "name": getattr(tool, "name", tool.__class__.__name__),
        "description": getattr(tool, "description", "") or "",
        "parameters": _tool_schema(tool),
    }


def _build_tool_prompt(prompt: str, tools: Iterable[Any]) -> str:
    tool_specs = [_tool_spec(tool) for tool in tools]
    return (
        "You are acting as an LLM with tool-calling support for an external orchestrator.\n"
        "Preserve the intent, constraints, and content of the original prompt below.\n"
        "Do not answer in natural-language prose outside the JSON envelope.\n"
        "Return only valid JSON so the orchestrator can either execute tool calls or accept the final answer.\n\n"
        "Output format:\n"
        "{\n"
        '  "tool_calls": [\n'
        '    {"name": "tool_name", "args": {"param": "value"}}\n'
        "  ]\n"
        "}\n"
        "or\n"
        '{\n'
        '  "final_answer": "your response"\n'
        "}\n\n"
        "Available tools:\n"
        f"{json.dumps(tool_specs, indent=2, ensure_ascii=True, sort_keys=True)}\n\n"
        "Original prompt to follow:\n"
        "<<BEGIN_ORIGINAL_PROMPT>>\n"
        f"{prompt}\n"
        "<<END_ORIGINAL_PROMPT>>"
    )


def _coerce_tool_calls(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    raw_tool_calls = payload.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return []

    normalized = []
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            continue

        name = raw_call.get("name")
        args = raw_call.get("args", {})
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(args, dict):
            continue

        normalized.append(
            {
                "name": name,
                "args": args,
                "id": raw_call.get("id") or f"call_{uuid.uuid4().hex}",
                "type": "tool_call",
            }
        )

    return normalized


class OpenCodeClient(BaseLLMClient):
    """Compatibility wrapper for a local `opencode run` command."""

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "opencode",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        return self

    def validate_model(self) -> bool:
        # OpenCode is treated as a black box; model naming is caller-defined.
        return True

    def invoke(self, input: Any, config=None, **kwargs) -> AIMessage:
        prompt = self._normalize_prompt(input)
        content = self._run_binary(prompt)
        return AIMessage(content=content)

    def bind_tools(self, tools: Iterable[Any]) -> RunnableLambda:
        tool_list = list(tools)

        def _invoke_bound(input: Any, config=None, **kwargs) -> AIMessage:
            prompt = self._normalize_prompt(input)
            tool_prompt = _build_tool_prompt(prompt, tool_list)
            raw_output = self._run_binary(tool_prompt)

            try:
                payload = json.loads(_extract_first_json_value(raw_output))
            except ValueError:
                return AIMessage(content=raw_output)

            tool_calls = _coerce_tool_calls(payload)
            if tool_calls:
                return AIMessage(content="", tool_calls=tool_calls)

            final_answer = payload.get("final_answer")
            if isinstance(final_answer, str):
                return AIMessage(content=final_answer)

            return AIMessage(content=raw_output)

        return RunnableLambda(_invoke_bound)

    def with_structured_output(self, schema: type) -> RunnableLambda:
        def _invoke_structured(input: Any, config=None, **kwargs) -> Any:
            prompt = self._normalize_prompt(input)
            structured_prompt = (
                "You are acting as an LLM with structured-output support for an external orchestrator.\n"
                "Preserve the intent, constraints, and content of the original prompt below.\n"
                "Return only valid JSON that matches this schema. "
                "Do not include markdown, code fences, or commentary.\n\n"
                "Schema:\n"
                f"{_schema_json(schema)}\n\n"
                "Original prompt to follow:\n"
                "<<BEGIN_ORIGINAL_PROMPT>>\n"
                f"{prompt}\n"
                "<<END_ORIGINAL_PROMPT>>"
            )
            raw_output = self._run_binary(structured_prompt)
            payload = _extract_first_json_value(raw_output)
            return _validate_structured_output(schema, payload)

        return RunnableLambda(_invoke_structured)

    def _run_binary(self, prompt: str) -> str:
        command = [*_DEFAULT_OPENCODE_COMMAND]
        if self.model:
            command.extend(["--model", self.model])
        command.append(prompt)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def _normalize_prompt(self, input: Any) -> str:
        if isinstance(input, str):
            return input
        if isinstance(input, BaseMessage):
            return self._serialize_messages([input])
        if isinstance(input, list):
            return self._serialize_messages(input)
        if hasattr(input, "to_messages"):
            return self._serialize_messages(input.to_messages())
        return str(input)

    def _serialize_messages(self, messages: Iterable[Any]) -> str:
        serialized = []

        for message in messages:
            if isinstance(message, BaseMessage):
                role = getattr(message, "type", message.__class__.__name__)
                content = message.content
            elif isinstance(message, dict):
                role = message.get("role", "message")
                content = message.get("content", "")
            else:
                role = message.__class__.__name__
                content = str(message)

            serialized.append(f"{role.upper()}:\n{self._stringify_content(content)}")

        return "\n\n".join(serialized)

    @staticmethod
    def _stringify_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=True))
            return "\n".join(part for part in parts if part)
        if isinstance(content, dict):
            return json.dumps(content, indent=2, ensure_ascii=True, sort_keys=True)
        return str(content)
