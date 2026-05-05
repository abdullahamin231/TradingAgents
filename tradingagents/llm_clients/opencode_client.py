import json
import subprocess
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
        def _invoke_bound(input: Any, config=None, **kwargs) -> AIMessage:
            return self.invoke(input, config=config, **kwargs)

        return RunnableLambda(_invoke_bound)

    def with_structured_output(self, schema: type) -> RunnableLambda:
        def _invoke_structured(input: Any, config=None, **kwargs) -> Any:
            prompt = self._normalize_prompt(input)
            structured_prompt = (
                "Return only valid JSON that matches this schema. "
                "Do not include markdown, code fences, or commentary.\n\n"
                "Schema:\n"
                f"{_schema_json(schema)}\n\n"
                "Prompt:\n"
                f"{prompt}"
            )
            raw_output = self._run_binary(structured_prompt)
            payload = _extract_first_json_value(raw_output)
            return _validate_structured_output(schema, payload)

        return RunnableLambda(_invoke_structured)

    def _run_binary(self, prompt: str) -> str:
        completed = subprocess.run(
            [*_DEFAULT_OPENCODE_COMMAND, prompt],
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
