from unittest.mock import patch

import httpx
import pytest
import respx

from carhealth import services
from carhealth.config import Settings


@pytest.fixture(autouse=True)
def reset_mot_token_cache():
    services._mot_token = None
    services._mot_token_expires_at = 0
    services._low_quota_warned = False
    yield


def make_settings(
    zyfy_api_key="test-zyfy-key",
    mot_client_id="client-id",
    mot_client_secret="client-secret",
    mot_api_key="mot-key",
    mot_token_url="https://login.example/token",
    mot_scope_url="https://scope.example/.default",
    ntfy_url=None,
    ntfy_topic=None,
    ntfy_token=None,
):
    return Settings(
        zyfy_api_key=zyfy_api_key,
        mot_client_id=mot_client_id,
        mot_client_secret=mot_client_secret,
        mot_api_key=mot_api_key,
        mot_token_url=mot_token_url,
        mot_scope_url=mot_scope_url,
        ntfy_url=ntfy_url,
        ntfy_topic=ntfy_topic,
        ntfy_token=ntfy_token,
    )


def make_ntfy_settings(**overrides):
    return make_settings(
        ntfy_url="https://ntfy.example",
        ntfy_topic="car-health-quota",
        ntfy_token="tk_test",
        **overrides,
    )


class TestGetZyfyData:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_error(self):
        result = await services.get_zyfy_data("AB12CDE", make_settings(zyfy_api_key=None))
        assert "error" in result
        assert "ZYFY_API_KEY" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(200, json={"registration": "AB12CDE", "make": "TOYOTA"})
        )
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert result == {"registration": "AB12CDE", "make": "TOYOTA"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_through_enrichment_pending(self):
        route = respx.get("https://zyfy.uk/v1/vehicle/AB12CDE")
        route.side_effect = [
            httpx.Response(200, json={"enrichmentPending": True}, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"enrichmentPending": False, "make": "TOYOTA"}),
        ]
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert result["make"] == "TOYOTA"
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_gives_up_after_max_attempts_still_pending(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(200, json={"enrichmentPending": True}, headers={"Retry-After": "0"})
        )
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert "error" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_quota_exhausted_returns_immediately_with_reset_date(self):
        route = respx.get("https://zyfy.uk/v1/vehicle/AB12CDE")
        route.mock(
            return_value=httpx.Response(
                429,
                json={
                    "code": "quota_exhausted",
                    "error": "Monthly request limit reached.",
                    "limit": 100,
                    "used": 100,
                    "resets": "2026-09-10T11:25:16.457937Z",
                },
            )
        )
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert "temporarily unavailable" in result["error"].lower()
        assert "10 Sep 2026" in result["error"]
        assert "2026-09-10T11:25:16.457937Z" not in result["error"]  # raw ISO timestamp, not user-facing
        assert route.call_count == 1  # no retry loop for a hard monthly cap

    @pytest.mark.asyncio
    @respx.mock
    async def test_quota_exhausted_falls_back_gracefully_without_resets_field(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(429, json={"code": "quota_exhausted", "limit": 100, "used": 100})
        )
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert "temporarily unavailable" in result["error"].lower()
        assert "later this month" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_plain_429_without_quota_code_still_retries(self):
        route = respx.get("https://zyfy.uk/v1/vehicle/AB12CDE")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"make": "TOYOTA"}),
        ]
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert result["make"] == "TOYOTA"
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_returns_invalid_key_error(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(return_value=httpx.Response(401))
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert "invalid" in result["error"].lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_returns_error(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(return_value=httpx.Response(500, text="boom"))
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert "error" in result
        assert "500" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_error_returns_error(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(side_effect=httpx.ConnectError("no route"))
        result = await services.get_zyfy_data("AB12CDE", make_settings())
        assert "error" in result
        assert "Could not reach Zyfy" in result["error"]


class TestLowQuotaWarning:
    @pytest.mark.asyncio
    @respx.mock
    async def test_warns_once_when_remaining_at_or_below_threshold(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(
                200,
                json={"make": "TOYOTA"},
                headers={"X-Quota-Remaining": "5", "X-Quota-Limit": "100", "X-Quota-Resets": "2026-09-10"},
            )
        )
        with patch("carhealth.services.notify.send") as send:
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())
        assert send.called
        assert "5/100" in send.call_args.kwargs["body"]
        assert "2026-09-10" in send.call_args.kwargs["body"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_warn_when_remaining_above_threshold(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(
                200, json={"make": "TOYOTA"}, headers={"X-Quota-Remaining": "50", "X-Quota-Limit": "100"}
            )
        )
        with patch("carhealth.services.notify.send") as send:
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())
        assert not send.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_warns_only_once_per_depletion_cycle(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(
                200, json={"make": "TOYOTA"}, headers={"X-Quota-Remaining": "3", "X-Quota-Limit": "100"}
            )
        )
        with patch("carhealth.services.notify.send") as send:
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())
        assert send.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_rearms_after_quota_resets(self):
        route = respx.get("https://zyfy.uk/v1/vehicle/AB12CDE")

        def resp(remaining):
            return httpx.Response(
                200, json={"make": "TOYOTA"}, headers={"X-Quota-Remaining": remaining, "X-Quota-Limit": "100"}
            )

        route.side_effect = [resp("2"), resp("100"), resp("1")]
        with patch("carhealth.services.notify.send") as send:
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())  # low -> warns
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())  # reset -> re-arms
            await services.get_zyfy_data("AB12CDE", make_ntfy_settings())  # low again -> warns
        assert send.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_quota_headers_does_not_crash(self):
        respx.get("https://zyfy.uk/v1/vehicle/AB12CDE").mock(
            return_value=httpx.Response(200, json={"make": "X"})
        )
        with patch("carhealth.services.notify.send") as send:
            result = await services.get_zyfy_data("AB12CDE", make_ntfy_settings())
        assert result["make"] == "X"
        assert not send.called


class TestGetMotData:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_error(self):
        result = await services.get_mot_data("AB12CDE", make_settings(mot_api_key=None))
        assert "error" in result
        assert "MOT_API_KEY" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_token_credentials_returns_auth_error(self):
        result = await services.get_mot_data("AB12CDE", make_settings(mot_client_id=None))
        assert "Could not authenticate" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_success_returns_dict_response(self):
        respx.post("https://login.example/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})
        )
        respx.get("https://history.mot.api.gov.uk/v1/trade/vehicles/registration/AB12CDE").mock(
            return_value=httpx.Response(200, json={"registration": "AB12CDE", "motTests": []})
        )
        result = await services.get_mot_data("AB12CDE", make_settings())
        assert result["registration"] == "AB12CDE"

    @pytest.mark.asyncio
    @respx.mock
    async def test_success_unwraps_list_response(self):
        respx.post("https://login.example/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})
        )
        respx.get("https://history.mot.api.gov.uk/v1/trade/vehicles/registration/AB12CDE").mock(
            return_value=httpx.Response(200, json=[{"registration": "AB12CDE"}])
        )
        result = await services.get_mot_data("AB12CDE", make_settings())
        assert result == {"registration": "AB12CDE"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_list_response_is_not_found(self):
        respx.post("https://login.example/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})
        )
        respx.get("https://history.mot.api.gov.uk/v1/trade/vehicles/registration/AB12CDE").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await services.get_mot_data("AB12CDE", make_settings())
        assert "No MOT history" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_failure_returns_auth_error(self):
        respx.post("https://login.example/token").mock(return_value=httpx.Response(401))
        result = await services.get_mot_data("AB12CDE", make_settings())
        assert "Could not authenticate" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_returns_not_found(self):
        respx.post("https://login.example/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})
        )
        respx.get("https://history.mot.api.gov.uk/v1/trade/vehicles/registration/AB12CDE").mock(
            return_value=httpx.Response(404)
        )
        result = await services.get_mot_data("AB12CDE", make_settings())
        assert "No MOT history" in result["error"]
