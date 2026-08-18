import asyncio
import time
from urllib.parse import quote

import httpx

from . import notify
from .config import Settings, get_settings

ZYFY_URL = "https://zyfy.uk/v1/vehicle/{reg}"
MOT_URL = "https://history.mot.api.gov.uk/v1/trade/vehicles/registration/{reg}"

_mot_token: str | None = None
_mot_token_expires_at: float = 0

# Below this many requests left, push a one-time warning per depletion cycle.
LOW_QUOTA_THRESHOLD = 10
_low_quota_warned = False


def _check_quota_headers(resp: httpx.Response, settings: Settings) -> None:
    """Zyfy sends X-Quota-* headers on every response, success or not - use
    them to warn before the quota actually runs out, not just after.

    Fires once per depletion cycle: stays quiet on every call while already
    warned, and re-arms itself the moment remaining rises back above the
    threshold (i.e. the monthly quota reset).
    """
    global _low_quota_warned
    try:
        remaining = int(resp.headers["X-Quota-Remaining"])
        limit = int(resp.headers["X-Quota-Limit"])
    except (KeyError, ValueError):
        return

    if remaining > LOW_QUOTA_THRESHOLD:
        _low_quota_warned = False
        return

    if _low_quota_warned:
        return
    _low_quota_warned = True

    resets = resp.headers.get("X-Quota-Resets", "unknown")
    notify.send(
        subject="Zyfy quota running low",
        body=f"{remaining}/{limit} requests left this month - resets {resets}",
        tags="warning",
        priority="high",
        settings=settings,
    )


async def get_zyfy_data(reg: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    api_key = settings.zyfy_api_key
    if not api_key:
        return {"error": "ZYFY_API_KEY not set in .env"}

    headers = {"X-Api-Key": api_key}
    url = ZYFY_URL.format(reg=quote(reg))

    for _ in range(5):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
        except httpx.RequestError as e:
            return {"error": f"Could not reach Zyfy API: {e}"}

        _check_quota_headers(resp, settings)

        if resp.status_code == 429:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if body.get("code") == "quota_exhausted":
                # A hard monthly cap, not backpressure - retrying just burns 50s
                # to land on the same answer. Surface the real reason and the
                # date it lifts instead of a generic timeout.
                used, limit = body.get("used", "?"), body.get("limit", "?")
                resets = body.get("resets", "later")
                return {"error": f"Zyfy monthly quota reached ({used}/{limit} used) - resets {resets}"}
            await asyncio.sleep(min(int(resp.headers.get("Retry-After", "5")), 10))
            continue
        if resp.status_code == 401:
            return {"error": "Zyfy API key invalid"}
        if resp.status_code != 200:
            return {"error": f"Zyfy API error {resp.status_code}: {resp.text}"}

        data = resp.json()
        if data.get("enrichmentPending"):
            await asyncio.sleep(min(int(resp.headers.get("Retry-After", "5")), 10))
            continue
        return data

    return {"error": "Zyfy enrichment did not complete in time — try again shortly"}


async def _get_mot_token(settings: Settings) -> str | None:
    global _mot_token, _mot_token_expires_at

    now = time.time()
    if _mot_token and _mot_token_expires_at > now + 30:
        return _mot_token

    client_id = settings.mot_client_id
    client_secret = settings.mot_client_secret
    token_url = settings.mot_token_url
    scope_url = settings.mot_scope_url
    if client_id is None or client_secret is None or token_url is None or scope_url is None:
        return None

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope_url,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(token_url, data=data)
    except httpx.RequestError:
        return None

    if resp.status_code != 200:
        return None

    body = resp.json()
    _mot_token = body["access_token"]
    _mot_token_expires_at = now + body.get("expires_in", 3600)
    return _mot_token


async def get_mot_data(reg: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    api_key = settings.mot_api_key
    if not api_key:
        return {"error": "MOT_API_KEY not set in .env"}

    token = await _get_mot_token(settings)
    if not token:
        return {"error": "Could not authenticate with MOT History API - check MOT_CLIENT_ID/SECRET in .env"}

    headers = {"Authorization": f"Bearer {token}", "x-api-key": api_key}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(MOT_URL.format(reg=quote(reg)), headers=headers)
    except httpx.RequestError as e:
        return {"error": f"Could not reach MOT API: {e}"}

    if resp.status_code == 404:
        return {"error": "No MOT history found for this vehicle"}
    if resp.status_code != 200:
        return {"error": f"MOT API error {resp.status_code}: {resp.text}"}

    data = resp.json()
    if isinstance(data, list):
        return data[0] if data else {"error": "No MOT history found for this vehicle"}
    return data
