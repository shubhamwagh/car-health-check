import asyncio
import time
from urllib.parse import quote

import httpx

from .config import Settings, get_settings

ZYFY_URL = "https://zyfy.uk/v1/vehicle/{reg}"
MOT_URL = "https://history.mot.api.gov.uk/v1/trade/vehicles/registration/{reg}"

_mot_token: str | None = None
_mot_token_expires_at: float = 0


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

        if resp.status_code == 429:
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
