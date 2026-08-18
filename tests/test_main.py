from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from carhealth.main import app

client = TestClient(app)

# Real Zyfy responses always include every signal/summary key (null when
# unknown, per their docs) — these defaults keep test fixtures realistic so
# Jinja sees an explicit None instead of a genuinely missing dict key.
FULL_SIGNALS = {
    "co2EmissionsGPerKm": None,
    "euroEmissionStandard": None,
    "ulezCompliant": None,
    "taxStatus": None,
    "taxDueDate": None,
    "taxDaysRemaining": None,
    "vedBand": None,
    "vedAnnualCostGbp": None,
    "motStatus": None,
    "motExpiryDate": None,
    "motDaysRemaining": None,
    "imminentMot": False,
    "markedForExport": False,
    "v5cLastIssued": None,
    "hasOutstandingRecall": None,
    "odometerTrend": None,
    "latestOdometerMiles": None,
    "typicalAnnualMileageMiles": None,
    "odometerVsFleetAverage": None,
    "drivetrainStressProfile": None,
    "motPassRate": None,
    "totalMotTests": 0,
    "totalMotFailures": 0,
    "totalAdvisoryCount": None,
    "totalFailureItemCount": None,
    "latestAdvisoryCount": None,
    "latestFailureItemCount": None,
    "dangerousDefectEver": False,
    "highFailureHistory": False,
    "advisoryTrend": None,
    "advisoryMomentum": None,
    "daysSinceLastFailure": None,
    "failuresLast24Months": None,
    "advisoriesLast3Tests": None,
    "firstMotDate": None,
    "lastMotDate": None,
    "lastMotResult": None,
    "firstMotDue": None,
    "failureClusters": None,
    "repeatFailureCount": None,
    "advisoryClusters": None,
}

FULL_SUMMARY = {
    "buyRecommendation": None,
    "vehicleRiskLevel": None,
    "motRiskLevel": None,
    "conditionBand": None,
    "maintenanceBand": None,
    "mileageAnomalyRisk": None,
    "colourChangeIndicated": False,
    "aboveAverageAdvisories": False,
}

FULL_SCORES = {
    "conditionPercentile": None,
    "maintenancePercentile": None,
    "failureRateRatio": None,
    "advisoryRateRatio": None,
    "benchmarkSampleSize": None,
    "avgFailuresPerTestForMMY": None,
    "avgAdvisoriesPerTestForMMY": None,
    "offRoadLikelihoodScore": None,
}

FULL_FLEET_FAILURE_PROFILE = {"mileageBand": None, "sampleSize": None, "topFailures": None}
FULL_FLEET_ADVISORY_PROFILE = {"topAdvisories": None}


def build_vehicle(signals=None, summary=None, scores=None, **top_level):
    return {
        "signals": {**FULL_SIGNALS, **(signals or {})},
        "summary": {**FULL_SUMMARY, **(summary or {})},
        "scores": {**FULL_SCORES, **(scores or {})},
        "fleetFailureProfile": dict(FULL_FLEET_FAILURE_PROFILE),
        "fleetAdvisoryProfile": dict(FULL_FLEET_ADVISORY_PROFILE),
        **top_level,
    }


def mock_services(vehicle=None, mot=None):
    """Patch the service calls carhealth.main already imported by name."""
    vehicle = vehicle if vehicle is not None else {"error": "ZYFY_API_KEY not set in .env"}
    mot = mot if mot is not None else {"error": "MOT_API_KEY not set in .env"}
    return (
        patch("carhealth.main.get_zyfy_data", new=AsyncMock(return_value=vehicle)),
        patch("carhealth.main.get_mot_data", new=AsyncMock(return_value=mot)),
    )


def test_home_page_loads():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Car Health Check" in resp.text


def test_report_rejects_invalid_registration_format():
    zyfy_patch, mot_patch = mock_services()
    with zyfy_patch as zyfy_mock, mot_patch as mot_mock:
        resp = client.get("/report", params={"reg": "!!not-a-plate!!"})
        assert resp.status_code == 200
        assert "Invalid registration number format" in resp.text
        assert resp.headers["X-No-Cache"] == "1"
        zyfy_mock.assert_not_called()
        mot_mock.assert_not_called()


def test_report_normalizes_registration_before_calling_services():
    zyfy_patch, mot_patch = mock_services()
    with zyfy_patch as zyfy_mock, mot_patch as mot_mock:
        client.get("/report", params={"reg": "ll68 jvg"})
        zyfy_mock.assert_awaited_once_with("LL68JVG")
        mot_mock.assert_awaited_once_with("LL68JVG")


def test_report_shows_vehicle_error_without_crashing():
    zyfy_patch, mot_patch = mock_services(vehicle={"error": "ZYFY_API_KEY not set in .env"})
    with zyfy_patch, mot_patch:
        resp = client.get("/report", params={"reg": "AB12CDE"})
        assert resp.status_code == 200
        assert "ZYFY_API_KEY not set in .env" in resp.text
        # An error page must never be cached for 24h behind the nginx cache -
        # it's still HTTP 200, so status code alone can't signal "don't cache this".
        assert resp.headers["X-No-Cache"] == "1"


def test_report_renders_vehicle_data():
    vehicle = build_vehicle(
        registration="LL68JVG",
        make="TOYOTA",
        model="AURIS",
        colour="BLACK",
        vehicleType="car",
        yearOfManufacture=2018,
        monthOfFirstRegistration="2018-11",
        vehicleAgeYears=8.5,
        fuelType="hybrid_electric",
        engineCapacityCc=1798,
        summary={"buyRecommendation": "good"},
        signals={"co2EmissionsGPerKm": 94, "taxStatus": "taxed", "motStatus": "valid"},
    )
    mot = {"model": "AURIS", "motTests": []}
    zyfy_patch, mot_patch = mock_services(vehicle=vehicle, mot=mot)
    with zyfy_patch, mot_patch:
        resp = client.get("/report", params={"reg": "LL68JVG"})
        assert resp.status_code == 200
        assert "TOYOTA" in resp.text
        assert "94" in resp.text
        assert "No MOT tests on record" in resp.text
        assert "X-No-Cache" not in resp.headers


def test_report_renders_mileage_chart_and_history_when_tests_present():
    vehicle = build_vehicle(make="TOYOTA", vehicleAgeYears=5.0)
    mot = {
        "model": "AURIS",
        "motTests": [
            {
                "completedDate": "2021-11-02T12:05:43.000Z",
                "testResult": "PASSED",
                "odometerValue": "7301",
                "odometerUnit": "MI",
                "expiryDate": "2022-11-29",
                "motTestNumber": "737856994806",
                "defects": [],
            },
            {
                "completedDate": "2026-05-18T10:21:58.000Z",
                "testResult": "PASSED",
                "odometerValue": "72674",
                "odometerUnit": "MI",
                "expiryDate": "2027-05-25",
                "motTestNumber": "866603947603",
                "defects": [],
            },
        ],
    }
    zyfy_patch, mot_patch = mock_services(vehicle=vehicle, mot=mot)
    with zyfy_patch, mot_patch:
        resp = client.get("/report", params={"reg": "LL68JVG"})
        assert resp.status_code == 200
        assert "Mileage history" in resp.text
        assert "65,373 mi" in resp.text  # delta between the two odometer readings
