# Car Health Check (UK)

Free vehicle health report for UK-reg cars — tax, MOT status, MOT history,
advisories, and buyer risk signals — using official/authoritative data
sources. No paid services.

## What you get

- **Vehicle info & performance** — make, model, engine, fuel, CO2 (with a colour band)
- **Road tax** — status, due date, VED band/cost
- **MOT** — status, expiry, full pass/fail history with mileage and defects, grouped by test day
- **Buying signal** — buy recommendation, risk level, odometer trend, fleet comparison (how this car compares to others of the same make/model/year)

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone <this repo>
cd car-health-check
uv sync
cp .env.example .env
```

Fill in `.env`:

| Variable | Get it from |
|---|---|
| `ZYFY_API_KEY` | [zyfy.uk/signup](https://zyfy.uk/signup) — free tier, instant |
| `MOT_CLIENT_ID`, `MOT_CLIENT_SECRET`, `MOT_API_KEY` | [documentation.history.mot.api.gov.uk](https://documentation.history.mot.api.gov.uk/mot-history-api/register) — free, manual approval (1–3 days) |

The app works with tax/vehicle info only if the MOT credentials aren't ready
yet — the MOT section will just show an error until filled in.

## Run

```bash
uv run car-health-check --reload
```

Open http://127.0.0.1:8000, enter a reg number.

Options: `--host`, `--port`, `--reload` (auto-reload for development).

## Run with Docker

```bash
docker build -t car-health-check .
docker run -p 8000:8000 --env-file .env car-health-check
```

## Tests

```bash
uv run pytest
```

Runs the full suite with coverage (`--cov`). CI runs this on every push/PR
across Python 3.10–3.13.

## Project layout

```
src/carhealth/     application package (FastAPI app, services, templates)
tests/             pytest suite
Dockerfile         multi-stage build, runs as non-root
.github/workflows/ CI (test+coverage) and multi-arch (amd64/arm64) image build
```
