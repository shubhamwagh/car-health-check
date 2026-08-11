from datetime import datetime

from carhealth.charts import (
    build_mileage_chart,
    buyrec_status,
    co2_band,
    co2_status,
    defect_label,
    fmt_date,
    format_age,
    group_mot_history,
    humanize,
    momentum_status,
    odometer_status,
    parse_date,
    ratio_status,
    risk_status,
    riskscore_status,
)


class TestParseDate:
    def test_none_and_empty(self):
        assert parse_date(None) is None
        assert parse_date("") is None

    def test_plain_date(self):
        assert parse_date("2025-01-01") == datetime(2025, 1, 1)

    def test_z_suffix_three_fractional_digits(self):
        dt = parse_date("2026-05-18T10:21:58.000Z")
        assert dt.year == 2026 and dt.month == 5 and dt.day == 18

    def test_five_fractional_digits_normalized_to_six(self):
        # Python's fromisoformat only accepts 3 or 6 fractional digits pre-3.11
        dt = parse_date("2026-08-11T11:26:20.36194+00:00")
        assert dt is not None
        assert dt.microsecond == 361940

    def test_garbage_returns_none(self):
        assert parse_date("not-a-date") is None


class TestFmtDate:
    def test_formats_known_date(self):
        assert fmt_date("2025-01-01") == "1 Jan 2025"

    def test_falls_back_to_raw_value_on_unparseable(self):
        assert fmt_date("garbage") == "garbage"

    def test_none_returns_dash(self):
        assert fmt_date(None) == "—"


class TestFormatAge:
    def test_none(self):
        assert format_age(None) == "—"

    def test_years_and_months(self):
        assert format_age(8.5833333) == "8 years 7 months"

    def test_singular_year_and_month(self):
        assert format_age(1 + 1 / 12) == "1 year 1 month"

    def test_whole_years_no_months(self):
        assert format_age(5.0) == "5 years"

    def test_less_than_a_month(self):
        assert format_age(0.01) == "0 months"


class TestHumanize:
    def test_none(self):
        assert humanize(None) == "—"

    def test_bool_true(self):
        assert humanize(True) == "Yes"

    def test_bool_false(self):
        assert humanize(False) == "No"

    def test_snake_case_string(self):
        assert humanize("possible_clocking") == "Possible Clocking"

    def test_number_passthrough(self):
        assert humanize(42) == "42"


class TestDefectLabel:
    def test_known_code(self):
        assert defect_label("PRS") == "Reason"
        assert defect_label("MAJOR") == "Major"

    def test_unknown_code_passthrough(self):
        assert defect_label("SOMETHING_NEW") == "SOMETHING_NEW"


class TestStatusMappers:
    def test_risk_status(self):
        assert risk_status("low") == "good"
        assert risk_status("medium") == "warning"
        assert risk_status("high") == "critical"
        assert risk_status(None) is None

    def test_buyrec_status(self):
        assert buyrec_status("good") == "good"
        assert buyrec_status("avoid") == "critical"

    def test_odometer_status(self):
        assert odometer_status("consistent") == "good"
        assert odometer_status("possible_clocking") == "critical"

    def test_momentum_status(self):
        assert momentum_status("improving") == "good"
        assert momentum_status("worsening") == "critical"
        assert momentum_status("stable") is None

    def test_ratio_status_bounds(self):
        assert ratio_status(None) is None
        assert ratio_status(0.8) == "good"
        assert ratio_status(1.0) == "warning"
        assert ratio_status(1.2) == "critical"

    def test_riskscore_status_bounds(self):
        assert riskscore_status(None) is None
        assert riskscore_status(0.1) == "good"
        assert riskscore_status(0.4) == "warning"
        assert riskscore_status(0.7) == "critical"


class TestCo2:
    def test_co2_band_percent(self):
        band = co2_band(94)
        assert band["value"] == 94.0
        assert band["percent"] == round(94 / 300 * 100, 1)

    def test_co2_band_clamps_above_max(self):
        band = co2_band(600)
        assert band["percent"] == 100.0

    def test_co2_band_invalid_returns_none(self):
        assert co2_band(None) is None
        assert co2_band("n/a") is None

    def test_co2_status_thresholds(self):
        assert co2_status(100)["level"] == "good"
        assert co2_status(140)["level"] == "warning"
        assert co2_status(200)["level"] == "critical"


class TestGroupMotHistory:
    def test_empty_list(self):
        assert group_mot_history([]) == []

    def test_single_pass(self):
        tests = [
            {
                "completedDate": "2024-04-17T12:21:04.000Z",
                "testResult": "PASSED",
                "odometerValue": "44333",
                "odometerUnit": "MI",
                "expiryDate": "2025-05-15",
                "motTestNumber": "611832648614",
                "defects": [],
            }
        ]
        history = group_mot_history(tests)
        assert len(history) == 1
        entry = history[0]
        assert entry["result"] == "PASSED"
        assert entry["results"] == ["PASSED"]
        assert entry["odometer"] == "44,333 mi"
        assert entry["expiry"] == "15 May 2025"
        assert entry["retested"] is False
        assert entry["defects"] == []

    def test_same_day_retest_groups_into_one_entry(self):
        # Real DVSA shape: a same-day fail then pass retest for one MOT.
        tests = [
            {
                "completedDate": "2026-05-18T10:21:58.000Z",
                "testResult": "PASSED",
                "odometerValue": "72674",
                "odometerUnit": "MI",
                "expiryDate": "2027-05-25",
                "motTestNumber": "866603947603",
                "defects": [],
            },
            {
                "completedDate": "2026-05-18T10:21:57.000Z",
                "testResult": "FAILED",
                "odometerValue": "72674",
                "odometerUnit": "MI",
                "expiryDate": None,
                "motTestNumber": "851263539457",
                "defects": [{"dangerous": False, "text": "Wheel fixing loose", "type": "PRS"}],
            },
        ]
        history = group_mot_history(tests)
        assert len(history) == 1
        entry = history[0]
        assert entry["retested"] is True
        # chronological order within the day: fail (10:21:57) before pass (10:21:58)
        assert entry["results"] == ["FAILED", "PASSED"]
        assert entry["result"] == "PASSED"
        assert entry["expiry"] == "25 May 2027"
        assert len(entry["defects"]) == 1

    def test_defects_deduplicated_across_entries(self):
        tests = [
            {
                "completedDate": "2025-01-01T00:00:00.000Z",
                "testResult": "FAILED",
                "odometerValue": "1000",
                "odometerUnit": "MI",
                "motTestNumber": "1",
                "defects": [{"dangerous": False, "text": "Same defect", "type": "MAJOR"}],
            },
            {
                "completedDate": "2025-01-01T01:00:00.000Z",
                "testResult": "PASSED",
                "odometerValue": "1000",
                "odometerUnit": "MI",
                "motTestNumber": "2",
                "defects": [{"dangerous": False, "text": "Same defect", "type": "MAJOR"}],
            },
        ]
        history = group_mot_history(tests)
        assert len(history[0]["defects"]) == 1

    def test_skips_entries_with_unparseable_date(self):
        tests = [{"completedDate": None, "testResult": "PASSED", "odometerValue": "1"}]
        assert group_mot_history(tests) == []


class TestBuildMileageChart:
    def _tests(self):
        return [
            {"completedDate": "2021-11-02T12:05:43.000Z", "odometerValue": "7301"},
            {"completedDate": "2023-05-16T13:19:35.000Z", "odometerValue": "13633"},
            {"completedDate": "2026-05-18T10:21:58.000Z", "odometerValue": "72674"},
        ]

    def test_fewer_than_two_points_returns_none(self):
        assert build_mileage_chart([{"completedDate": "2025-01-01", "odometerValue": "100"}]) is None
        assert build_mileage_chart([]) is None

    def test_basic_shape(self):
        chart = self._tests()
        result = build_mileage_chart(chart)
        assert result["test_count"] == 3
        assert result["delta_label"] == "65,373"
        assert len(result["points"]) == 3
        assert result["points"][0]["value"] == 7301
        assert result["points"][-1]["value"] == 72674

    def test_dedupes_same_day_readings(self):
        tests = self._tests() + [
            # same day as the last one, should not add a second point
            {"completedDate": "2026-05-18T18:00:00.000Z", "odometerValue": "72700"}
        ]
        result = build_mileage_chart(tests)
        assert result["test_count"] == 3

    def test_year_ticks_cover_each_distinct_year(self):
        result = build_mileage_chart(self._tests())
        years = {t["label"] for t in result["year_ticks"]}
        assert years == {"2021", "2023", "2026"}

    def test_points_are_chronologically_ascending(self):
        # feed them out of order; function must sort internally
        tests = list(reversed(self._tests()))
        result = build_mileage_chart(tests)
        values = [p["value"] for p in result["points"]]
        assert values == sorted(values)
