from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class DiscordConfig:
    webhook_url: str | None
    timeout_seconds: float = 10.0

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)


DEFAULT_DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/"
    "1508095891112857602/"
    "aQoD8gvuJVr-gYzgSPnB_jiK5mvO5Zc8fqNvha4SdErCvRhrUarhCn9Xt3mvE1fhG8tz"
)


def discord_config_from_env() -> DiscordConfig:
    return DiscordConfig(
        webhook_url=(os.getenv("DISCORD_WEBHOOK_URL") or DEFAULT_DISCORD_WEBHOOK_URL).strip() or None,
        timeout_seconds=float(os.getenv("DISCORD_TIMEOUT_SECONDS") or "10"),
    )


def send_discord_message(
    text: str,
    *,
    config: DiscordConfig | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    resolved = config or discord_config_from_env()
    if not resolved.enabled:
        return {"status": "skipped", "reason": "discord_not_configured"}

    message = text.strip()
    if len(message) > 2000:
        message = message[:1997].rstrip() + "..."

    client = session or requests.Session()
    separator = "&" if "?" in resolved.webhook_url else "?"
    response = client.post(
        f"{resolved.webhook_url}{separator}wait=true",
        json={
            "content": message,
        },
        timeout=resolved.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "status": "sent" if payload.get("id") else "failed",
        "discord_response": payload,
    }
