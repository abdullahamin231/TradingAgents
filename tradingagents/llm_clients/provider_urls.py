"""Shared provider URL helpers."""

from __future__ import annotations

import os


def get_ollama_base_url() -> str:
    """Return the best Ollama base URL for the current environment.

    Preference order:
    1. Explicit override via `TRADINGAGENTS_BACKEND_URL`
    2. Explicit override via `OLLAMA_BASE_URL`
    3. Compose service name when running inside Docker
    4. Local host fallback for non-container runs
    """
    return (
        os.getenv("TRADINGAGENTS_BACKEND_URL")
        or os.getenv("OLLAMA_BASE_URL")
        or ("http://ollama:11434/v1" if os.path.exists("/.dockerenv") else "http://localhost:11434/v1")
    )
