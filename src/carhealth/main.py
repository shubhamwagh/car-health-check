import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .charts import (
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
    ratio_status,
    risk_status,
    riskscore_status,
)
from .services import get_mot_data, get_zyfy_data

app = FastAPI(title="Car Health Check")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["fmtdate"] = fmt_date
templates.env.filters["formatage"] = format_age
templates.env.filters["defectlabel"] = defect_label
templates.env.filters["riskstatus"] = risk_status
templates.env.filters["buyrecstatus"] = buyrec_status
templates.env.filters["odometerstatus"] = odometer_status
templates.env.filters["momentumstatus"] = momentum_status
templates.env.filters["ratiostatus"] = ratio_status
templates.env.filters["riskscorestatus"] = riskscore_status
templates.env.filters["humanize"] = humanize

REG_RE = re.compile(r"^[A-Z0-9]{2,7}$")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/report", response_class=HTMLResponse)
async def report(request: Request, reg: str):
    reg_clean = reg.replace(" ", "").upper()

    if not REG_RE.match(reg_clean):
        error = {"error": "Invalid registration number format"}
        return templates.TemplateResponse(
            request,
            "report.html",
            {"reg": reg_clean, "vehicle": error, "mot": error},
        )

    vehicle = await get_zyfy_data(reg_clean)
    mot = await get_mot_data(reg_clean)

    mileage_chart = None
    mot_history = None
    if not mot.get("error") and mot.get("motTests"):
        mileage_chart = build_mileage_chart(mot["motTests"])
        mot_history = group_mot_history(mot["motTests"])

    co2 = None
    co2band = None
    if not vehicle.get("error"):
        co2_value = (vehicle.get("signals") or {}).get("co2EmissionsGPerKm")
        co2 = co2_status(co2_value)
        co2band = co2_band(co2_value)

    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "reg": reg_clean,
            "vehicle": vehicle,
            "mot": mot,
            "mileage_chart": mileage_chart,
            "mot_history": mot_history,
            "co2": co2,
            "co2band": co2band,
        },
    )
