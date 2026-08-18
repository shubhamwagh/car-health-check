"""Tests for the ntfy notification helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from carhealth import notify
from carhealth.config import Settings


def _settings(**overrides):
    defaults = {"ntfy_url": None, "ntfy_topic": None, "ntfy_token": None}
    defaults.update(overrides)
    return Settings(**defaults)


def test_send_skips_push_when_unconfigured():
    with patch("carhealth.notify.httpx.post") as post:
        notify.send(subject="x", body="y", settings=_settings())
    assert not post.called


def test_send_posts_to_configured_topic():
    settings = _settings(ntfy_url="https://ntfy.example", ntfy_topic="car-health-quota", ntfy_token="tk_abc")
    with patch("carhealth.notify.httpx.post") as post:
        post.return_value = MagicMock(raise_for_status=MagicMock())
        notify.send(
            subject="Zyfy quota running low",
            body="5/100 left",
            tags="warning",
            priority="high",
            settings=settings,
        )

    assert post.called
    url, kwargs = post.call_args[0][0], post.call_args[1]
    assert url == "https://ntfy.example/car-health-quota"
    assert kwargs["content"] == b"5/100 left"
    assert kwargs["headers"]["Authorization"] == "Bearer tk_abc"
    assert kwargs["headers"]["Title"] == "Zyfy quota running low"
    assert kwargs["headers"]["Priority"] == "high"
    assert kwargs["headers"]["Tags"] == "warning"


def test_send_swallows_network_errors():
    settings = _settings(ntfy_url="https://ntfy.example", ntfy_topic="t", ntfy_token="tk")
    with patch("carhealth.notify.httpx.post", side_effect=httpx.ConnectError("down")):
        notify.send(subject="x", body="y", settings=settings)  # must not raise
