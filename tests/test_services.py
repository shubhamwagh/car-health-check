import httpx
import pytest
import respx

from carhealth import services
from carhealth.config import Settings


@pytest.fixture(autouse=True)
def reset_mot_token_cache():
    services._mot_token = None
    services._mot_token_expires_at = 0
    yield


def make_settings(
    zyfy_api_key="test-zyfy-key",
    mot_client_id="client-id",
    mot_client_secret="client-secret",
    mot_api_key="mot-key",
    mot_token_url="https://login.example/token",
    mot_scope_url="https://scope.example/.default",
):
    return Settings(
        zyfy_api_key=zyfy_api_key,
        mot_client_id=mot_client_id,
        mot_client_secret=mot_client_secret,
        mot_api_key=mot_api_key,
        mot_token_url=mot_token_url,
        mot_scope_url=mot_scope_url,
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
