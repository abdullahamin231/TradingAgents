import subprocess
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from pydantic import BaseModel

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import OpenCodeClient
from tradingagents.llm_clients.factory import create_llm_client


class _OpenCodeResponse(BaseModel):
    action: str
    confidence: int


@tool
def _sample_tool(ticker: str, days: int = 7) -> str:
    """Return sample tool output."""
    return f"{ticker}:{days}"


@pytest.mark.unit
class TestOpenCodeClient:
    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_invoke_returns_ai_message(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout=(
                '{"type":"step_start","timestamp":1778507973646,"sessionID":"ses_123","part":{"snapshot":"snap1"}}\n'
                '{"type":"text","timestamp":1778507976660,"sessionID":"ses_123","part":{"text":"binary output"}}\n'
                '{"type":"step_finish","timestamp":1778507976713,"sessionID":"ses_123","part":{"reason":"stop","messageID":"msg1","snapshot":"snap1","tokens":{"total":8869,"input":123,"output":8,"reasoning":34,"cache":{"write":0,"read":8704}},"cost":0}}\n'
            ),
            stderr="",
        )

        client = OpenCodeClient("any-model")
        result = client.invoke("Prompt text")

        assert isinstance(result, AIMessage)
        assert result.content == "binary output"
        assert result.additional_kwargs["opencode_usage"]["tokens"]["total"] == 8869
        assert mock_run.call_args.args[0] == ["opencode", "run", "--format", "json", "--model", "any-model", "--pure", "Prompt text"]

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_with_structured_output_parses_json(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout='```json\n{"action":"buy","confidence":92}\n```\n',
            stderr="",
        )

        client = OpenCodeClient("any-model")
        runnable = client.with_structured_output(_OpenCodeResponse)
        result = runnable.invoke("Return a trade decision")

        assert result == _OpenCodeResponse(action="buy", confidence=92)
        opencode_prompt = mock_run.call_args.args[0][-1]
        assert "Return a trade decision" in opencode_prompt
        assert '"title": "_OpenCodeResponse"' in opencode_prompt

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_with_structured_output_raises_on_parse_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout="not json at all",
            stderr="",
        )

        client = OpenCodeClient("any-model")
        runnable = client.with_structured_output(_OpenCodeResponse)

        with pytest.raises(ValueError):
            runnable.invoke("Return a trade decision")

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_bind_tools_is_chain_compatible(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout='{"final_answer":"plain report"}',
            stderr="",
        )

        client = OpenCodeClient("any-model")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "System guidance"),
                ("human", "{topic}"),
            ]
        )

        chain = prompt | client.bind_tools([_sample_tool])
        result = chain.invoke({"topic": "NVDA"})

        assert isinstance(result, AIMessage)
        assert result.content == "plain report"
        opencode_prompt = mock_run.call_args.args[0][-1]
        assert "SYSTEM:" in opencode_prompt
        assert "HUMAN:" in opencode_prompt
        assert "NVDA" in opencode_prompt
        assert '"name": "_sample_tool"' in opencode_prompt
        assert '"final_answer"' in opencode_prompt

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_bind_tools_returns_tool_calls(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout='{"tool_calls":[{"name":"_sample_tool","args":{"ticker":"AAPL","days":5}}]}',
            stderr="",
        )

        client = OpenCodeClient("any-model")
        result = client.bind_tools([_sample_tool]).invoke("Analyze AAPL")

        assert isinstance(result, AIMessage)
        assert result.content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "_sample_tool"
        assert result.tool_calls[0]["args"] == {"ticker": "AAPL", "days": 5}
        assert result.tool_calls[0]["type"] == "tool_call"
        assert result.tool_calls[0]["id"].startswith("call_")

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_bind_tools_falls_back_to_plain_text_when_json_missing(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout="plain report without json",
            stderr="",
        )

        client = OpenCodeClient("any-model")
        result = client.bind_tools([_sample_tool]).invoke("Analyze AAPL")

        assert isinstance(result, AIMessage)
        assert result.content == "plain report without json"
        assert result.tool_calls == []

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_invoke_serializes_message_lists(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout='{"type":"text","part":{"text":"ok"}}\n{"type":"step_finish","part":{"tokens":{"total":1,"input":1,"output":0,"reasoning":0,"cache":{"read":0,"write":0}},"cost":0}}',
            stderr="",
        )

        client = OpenCodeClient("any-model")
        client.invoke(
            [
                SystemMessage(content="You are concise."),
                HumanMessage(content="Summarize NVDA."),
            ]
        )

        opencode_prompt = mock_run.call_args.args[0][-1]
        assert "SYSTEM:" in opencode_prompt
        assert "HUMAN:" in opencode_prompt
        assert "Summarize NVDA." in opencode_prompt

    @patch("tradingagents.llm_clients.opencode_client.subprocess.run")
    def test_usage_callback_receives_usage_payload(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["binary", "run", "prompt"],
            returncode=0,
            stdout=(
                '{"type":"step_start","timestamp":1000,"sessionID":"ses_123","part":{"snapshot":"snap1"}}\n'
                '{"type":"text","timestamp":1500,"sessionID":"ses_123","part":{"text":"Hello."}}\n'
                '{"type":"step_finish","timestamp":2000,"sessionID":"ses_123","part":{"reason":"stop","messageID":"msg1","snapshot":"snap1","tokens":{"total":20,"input":5,"output":3,"reasoning":2,"cache":{"write":1,"read":9}},"cost":0.25}}\n'
            ),
            stderr="",
        )
        seen = []

        client = OpenCodeClient("any-model", usage_callback=seen.append)
        result = client.invoke("Prompt text")

        assert result.content == "Hello."
        assert seen[0]["time"] == {"start": 1000, "end": 2000}
        assert seen[0]["tokens"]["cache"] == {"read": 9, "write": 1}
        assert seen[0]["cost"] == 0.25


@pytest.mark.unit
class TestOpenCodeProviderIntegration:
    def test_factory_returns_opencode_client(self):
        client = create_llm_client(provider="opencode", model="local-binary")

        assert isinstance(client, OpenCodeClient)
        assert client.get_llm() is client
        assert client.model == "local-binary"

    def test_trading_graph_accepts_opencode_provider_config(self, tmp_path):
        config = dict(DEFAULT_CONFIG)
        config.update(
            {
                "llm_provider": "opencode",
                "deep_think_llm": "local-deep-binary",
                "quick_think_llm": "local-quick-binary",
                "data_cache_dir": str(tmp_path / "cache"),
                "results_dir": str(tmp_path / "reports"),
                "memory_log_path": str(tmp_path / "memory" / "log.md"),
            }
        )

        graph = TradingAgentsGraph(selected_analysts=["market"], config=config)

        assert isinstance(graph.deep_thinking_llm, OpenCodeClient)
        assert isinstance(graph.quick_thinking_llm, OpenCodeClient)
        assert graph.deep_thinking_llm.model == "local-deep-binary"
        assert graph.quick_thinking_llm.model == "local-quick-binary"
