from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str | None
    chat_id: str | None
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = 10.0

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


def telegram_config_from_env() -> TelegramConfig:
    return TelegramConfig(
        bot_token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None,
        chat_id=(os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None,
        api_base_url=(os.getenv("TELEGRAM_API_BASE_URL") or "https://api.telegram.org").rstrip("/"),
        timeout_seconds=float(os.getenv("TELEGRAM_TIMEOUT_SECONDS") or "10"),
    )


def send_telegram_message(
    text: str,
    *,
    config: TelegramConfig | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    resolved = config or telegram_config_from_env()
    if not resolved.enabled:
        return {"status": "skipped", "reason": "telegram_not_configured"}

    message = text.strip()
    if len(message) > 3900:
        message = message[:3897].rstrip() + "..."

    client = session or requests.Session()
    response = client.post(
        f"{resolved.api_base_url}/bot{resolved.bot_token}/sendMessage",
        json={
            "chat_id": resolved.chat_id,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=resolved.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "status": "sent" if payload.get("ok") else "failed",
        "telegram_response": payload,
    }
