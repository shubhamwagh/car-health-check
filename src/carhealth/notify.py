"""Notification helper - pushes to a self-hosted ntfy topic, logs either way."""

from __future__ import annotations

import logging

import httpx

from .config import Settings, get_settings

log = logging.getLogger(__name__)


def send(
    subject: str,
    body: str,
    tags: str = "",
    priority: str = "default",
    settings: Settings | None = None,
) -> None:
    log.info(f"Notification: {subject}")
    settings = settings or get_settings()
    if not (settings.ntfy_url and settings.ntfy_topic and settings.ntfy_token):
        log.debug("NTFY_URL/NTFY_TOPIC/NTFY_TOKEN not set - skipping push, logged only")
        return

    headers = {
        "Authorization": f"Bearer {settings.ntfy_token}",
        "Title": subject,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags

    try:
        resp = httpx.post(
            f"{settings.ntfy_url.rstrip('/')}/{settings.ntfy_topic}",
            content=body.encode("utf-8"),
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.warning(f"ntfy push failed: {exc}")
