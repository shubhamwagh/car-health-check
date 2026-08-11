import re
from datetime import datetime

_FRACTIONAL_SECONDS_RE = re.compile(r"\.(\d+)")


def parse_date(value):
    if not value:
        return None
    v = str(value).replace("Z", "+00:00")
    # Python 3.9's fromisoformat only accepts exactly 3 or 6 fractional-second
    # digits — normalize whatever the API sends (e.g. 5 digits) to 6.
    v = _FRACTIONAL_SECONDS_RE.sub(lambda m: "." + (m.group(1) + "000000")[:6], v, count=1)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def fmt_date(value):
    dt = parse_date(value)
    return dt.strftime("%-d %b %Y") if dt else (value or "—")


DEFECT_TYPE_LABELS = {
    "DANGEROUS": "Dangerous",
    "MAJOR": "Major",
    "MINOR": "Minor",
    "ADVISORY": "Advisory",
    "PRS": "Reason",
    "USER ENTERED": "Note",
}


def defect_label(type_code):
    return DEFECT_TYPE_LABELS.get(type_code, type_code)


def group_mot_history(mot_tests):
    groups = {}
    order = []
    for t in mot_tests:
        dt = parse_date(t.get("completedDate"))
        if not dt:
            continue
        day = dt.date()
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append((dt, t))

    history = []
    for day in order:
        entries = [t for _, t in sorted(groups[day], key=lambda x: x[0])]
        final = entries[-1]

        expiry = next((e["expiryDate"] for e in reversed(entries) if e.get("expiryDate")), None)

        odo_val, odo_unit = final.get("odometerValue"), (final.get("odometerUnit") or "mi").lower()
        try:
            odometer = f"{int(odo_val):,} {odo_unit}"
        except (TypeError, ValueError):
            odometer = f"{odo_val} {odo_unit}".strip()

        defects, seen = [], set()
        for e in entries:
            for d in e.get("defects") or []:
                key = (d.get("type"), d.get("text"))
                if key in seen:
                    continue
                seen.add(key)
                defects.append(d)

        history.append({
            "date": fmt_date(final.get("completedDate")),
            "result": final.get("testResult"),
            "results": [e.get("testResult") for e in entries],
            "odometer": odometer,
            "expiry": fmt_date(expiry) if expiry else None,
            "test_number": final.get("motTestNumber"),
            "retested": len(entries) > 1,
            "defects": defects,
        })
    return history


RISK_LEVEL_STATUS = {"low": "good", "medium": "warning", "high": "critical"}
BUY_RECOMMENDATION_STATUS = {"good": "good", "consider": "warning", "caution": "warning", "avoid": "critical"}
ODOMETER_TREND_STATUS = {
    "consistent": "good",
    "low_mileage": "good",
    "high_mileage": "warning",
    "possible_clocking": "critical",
}


def risk_status(value):
    return RISK_LEVEL_STATUS.get(value)


def buyrec_status(value):
    return BUY_RECOMMENDATION_STATUS.get(value)


def odometer_status(value):
    return ODOMETER_TREND_STATUS.get(value)


MOMENTUM_STATUS = {"improving": "good", "worsening": "critical"}


def momentum_status(value):
    return MOMENTUM_STATUS.get(value)


def ratio_status(value):
    if value is None:
        return None
    if value >= 1.2:
        return "critical"
    if value <= 0.8:
        return "good"
    return "warning"


def riskscore_status(value):
    if value is None:
        return None
    if value >= 0.6:
        return "critical"
    if value >= 0.3:
        return "warning"
    return "good"


def format_age(years_decimal):
    if years_decimal is None:
        return "—"
    total_months = round(years_decimal * 12)
    years, months = divmod(total_months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    return " ".join(parts) if parts else "0 months"


def humanize(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).replace("_", " ").title()


def co2_band(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    percent = round(max(0.0, min(1.0, v / 300.0)) * 100, 1)
    return {"value": v, "percent": percent}


def co2_status(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 120:
        return {"level": "good", "label": "Low emissions"}
    if v <= 160:
        return {"level": "warning", "label": "Moderate emissions"}
    return {"level": "critical", "label": "High emissions"}


def build_mileage_chart(mot_tests):
    points = []
    seen_days = set()
    for t in mot_tests:
        dt = parse_date(t.get("completedDate"))
        odo = t.get("odometerValue")
        if not dt or odo is None:
            continue
        day = dt.date()
        if day in seen_days:
            continue
        try:
            odo_val = int(odo)
        except (TypeError, ValueError):
            continue
        seen_days.add(day)
        points.append((dt, odo_val))
    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        return None

    width, height = 640, 220
    m_left, m_right, m_top, m_bottom = 56, 16, 20, 32
    plot_w = width - m_left - m_right
    plot_h = height - m_top - m_bottom

    min_dt, max_dt = points[0][0], points[-1][0]
    span = (max_dt - min_dt).total_seconds() or 1
    max_odo = max(v for _, v in points)
    y_max = max(max_odo * 1.15, 1000)

    def x_for(dt):
        return m_left + (dt - min_dt).total_seconds() / span * plot_w

    def y_for(v):
        return m_top + plot_h - (v / y_max * plot_h)

    coords = [
        {
            "x": round(x_for(dt), 1),
            "y": round(y_for(v), 1),
            "date": dt.strftime("%-d %b %Y"),
            "value": v,
            "value_label": f"{v:,}",
            "year": dt.year,
        }
        for dt, v in points
    ]

    line_seg = " L ".join(f"{c['x']},{c['y']}" for c in coords)
    baseline_y = m_top + plot_h
    area_path = f"M {coords[0]['x']},{baseline_y} L {line_seg} L {coords[-1]['x']},{baseline_y} Z"

    gridlines = [
        {"y": round(y_for(y_max * frac), 1), "label": f"{int(round(y_max * frac)):,}"}
        for frac in (0.0, 0.5, 1.0)
    ]

    year_ticks = []
    seen_years = set()
    for c in coords:
        if c["year"] in seen_years:
            continue
        seen_years.add(c["year"])
        year_ticks.append({"x": c["x"], "y": baseline_y, "label": str(c["year"])})

    return {
        "width": width,
        "height": height,
        "baseline_y": baseline_y,
        "line_path": f"M {line_seg}",
        "area_path": area_path,
        "points": coords,
        "gridlines": gridlines,
        "year_ticks": year_ticks,
        "delta_label": f"{coords[-1]['value'] - coords[0]['value']:,}",
        "test_count": len(coords),
    }
