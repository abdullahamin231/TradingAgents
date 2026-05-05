import importlib
import os
import unittest
from unittest.mock import patch

from cli import utils as cli_utils
from tradingagents.llm_clients.provider_urls import get_ollama_base_url


class TestOllamaBackendUrl(unittest.TestCase):
    def test_select_llm_provider_honors_llm_provider_env(self):
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "ollama",
                "TRADINGAGENTS_BACKEND_URL": "http://ollama:11434/v1",
            },
            clear=False,
        ):
            with patch.object(cli_utils.questionary, "select") as mock_select:
                provider, backend_url = cli_utils.select_llm_provider()

        self.assertEqual(provider, "ollama")
        self.assertEqual(backend_url, "http://ollama:11434/v1")
        mock_select.assert_not_called()

    def test_select_llm_provider_uses_backend_url_env(self):
        with patch.dict(
            "os.environ",
            {"TRADINGAGENTS_BACKEND_URL": "http://ollama:11434/v1"},
            clear=False,
        ):
            class _Prompt:
                def ask(self):
                    return ("ollama", "http://ollama:11434/v1")

            with patch.object(cli_utils.questionary, "select", return_value=_Prompt()):
                provider, backend_url = cli_utils.select_llm_provider()

        self.assertEqual(provider, "ollama")
        self.assertEqual(backend_url, "http://ollama:11434/v1")

    def test_default_config_reads_backend_url_env(self):
        with patch.dict(
            "os.environ",
            {"TRADINGAGENTS_BACKEND_URL": "http://ollama:11434/v1"},
            clear=False,
        ):
            import tradingagents.default_config as default_config

            reloaded = importlib.reload(default_config)

        self.assertEqual(reloaded.DEFAULT_CONFIG["backend_url"], "http://ollama:11434/v1")

    def test_default_config_keeps_storage_under_reports_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            import tradingagents.default_config as default_config

            reloaded = importlib.reload(default_config)

        results_dir = reloaded.DEFAULT_CONFIG["results_dir"]
        self.assertEqual(
            reloaded.DEFAULT_CONFIG["data_cache_dir"],
            os.path.join(results_dir, "cache"),
        )
        self.assertEqual(
            reloaded.DEFAULT_CONFIG["memory_log_path"],
            os.path.join(results_dir, "memory", "trading_memory.md"),
        )

    def test_get_ollama_base_url_uses_docker_hostname_when_unset(self):
        with patch.dict("os.environ", {}, clear=True), patch("os.path.exists", return_value=True):
            self.assertEqual(get_ollama_base_url(), "http://ollama:11434/v1")


if __name__ == "__main__":
    unittest.main()
