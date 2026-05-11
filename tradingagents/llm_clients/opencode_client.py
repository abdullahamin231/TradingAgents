import json
from pathlib import Path
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from .base_client import BaseLLMClient


_DEFAULT_OPENCODE_COMMAND = ("opencode", "run")


@dataclass
class OpenCodeRunResult:
    content: str
    usage: dict[str, Any] | None = None


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
        working_dir: Optional[str] = None,
        usage_callback: Any = None,
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()
        self.working_dir = working_dir
        self.usage_callback = usage_callback

    def get_llm(self) -> Any:
        return self

    def validate_model(self) -> bool:
        # OpenCode is treated as a black box; model naming is caller-defined.
        return True

    def invoke(self, input: Any, config=None, **kwargs) -> AIMessage:
        prompt = self._normalize_prompt(input)
        result = self._run_binary(prompt)
        return AIMessage(content=result.content, additional_kwargs=self._message_metadata(result.usage))

    def bind_tools(self, tools: Iterable[Any]) -> RunnableLambda:
        tool_list = list(tools)

        def _invoke_bound(input: Any, config=None, **kwargs) -> AIMessage:
            prompt = self._normalize_prompt(input)
            tool_prompt = _build_tool_prompt(prompt, tool_list)
            result = self._run_binary(tool_prompt)
            raw_output = result.content

            try:
                payload = json.loads(_extract_first_json_value(raw_output))
            except ValueError:
                return AIMessage(content=raw_output, additional_kwargs=self._message_metadata(result.usage))

            tool_calls = _coerce_tool_calls(payload)
            if tool_calls:
                return AIMessage(content="", tool_calls=tool_calls, additional_kwargs=self._message_metadata(result.usage))

            final_answer = payload.get("final_answer")
            if isinstance(final_answer, str):
                return AIMessage(content=final_answer, additional_kwargs=self._message_metadata(result.usage))

            return AIMessage(content=raw_output, additional_kwargs=self._message_metadata(result.usage))

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
            result = self._run_binary(structured_prompt)
            payload = _extract_first_json_value(result.content)
            return _validate_structured_output(schema, payload)

        return RunnableLambda(_invoke_structured)

    def _run_binary(self, prompt: str) -> OpenCodeRunResult:
        command = [*_DEFAULT_OPENCODE_COMMAND]
        command.extend(["--format", "json"])
        if self.model:
            command.extend(["--model", self.model])
        command.append("--pure")
        command.append(prompt)
        cwd = None
        if self.working_dir:
            cwd_path = Path(self.working_dir)
            cwd_path.mkdir(parents=True, exist_ok=True)
            cwd = str(cwd_path)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        if completed.stderr:
            print(f"OpenCode stderr: {completed.stderr}")
        return self._parse_run_output(completed.stdout)

    def _parse_run_output(self, stdout: str) -> OpenCodeRunResult:
        stripped = stdout.strip()
        if not stripped:
            return OpenCodeRunResult(content="")

        events: list[dict[str, Any]] = []
        saw_json = False
        for line in stdout.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
                saw_json = True

        if not saw_json:
            return OpenCodeRunResult(content=stripped)

        text_parts: list[str] = []
        step_start: dict[str, Any] | None = None
        step_finish: dict[str, Any] | None = None

        for event in events:
            event_type = event.get("type")
            part = event.get("part") if isinstance(event.get("part"), dict) else {}
            if event_type == "text":
                text = part.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
            elif event_type == "step_start":
                step_start = event
            elif event_type == "step_finish":
                step_finish = event

        content = "".join(text_parts).strip()
        if not content:
            content = stripped

        usage = self._build_usage_payload(step_start, step_finish)
        if usage and callable(self.usage_callback):
            self.usage_callback(usage)

        return OpenCodeRunResult(content=content, usage=usage)

    def _build_usage_payload(
        self,
        step_start: dict[str, Any] | None,
        step_finish: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        finish_part = step_finish.get("part") if isinstance(step_finish, dict) and isinstance(step_finish.get("part"), dict) else {}
        start_part = step_start.get("part") if isinstance(step_start, dict) and isinstance(step_start.get("part"), dict) else {}

        if not finish_part:
            return None

        tokens = finish_part.get("tokens") if isinstance(finish_part.get("tokens"), dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}

        usage = {
            "provider": self.provider,
            "model": self.model,
            "session_id": (
                step_finish.get("sessionID")
                if isinstance(step_finish, dict) and step_finish.get("sessionID")
                else step_start.get("sessionID") if isinstance(step_start, dict) else None
            ),
            "message_id": finish_part.get("messageID"),
            "reason": finish_part.get("reason"),
            "cost": finish_part.get("cost"),
            "tokens": {
                "total": tokens.get("total", 0),
                "input": tokens.get("input", 0),
                "output": tokens.get("output", 0),
                "reasoning": tokens.get("reasoning", 0),
                "cache": {
                    "read": cache.get("read", 0),
                    "write": cache.get("write", 0),
                },
            },
            "time": {
                "start": step_start.get("timestamp") if isinstance(step_start, dict) else None,
                "end": step_finish.get("timestamp") if isinstance(step_finish, dict) else None,
            },
            "snapshot": finish_part.get("snapshot") or start_part.get("snapshot"),
        }
        return usage

    @staticmethod
    def _message_metadata(usage: dict[str, Any] | None) -> dict[str, Any]:
        if not usage:
            return {}
        return {"opencode_usage": usage}

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
