# Car Health Check (UK)

Free vehicle report for UK reg plates: tax status, MOT history, and some
buyer risk signals (odometer trend, fleet comparison, buy recommendation).
Uses the DVSA MOT History API and Zyfy's Vehicle Intelligence API. No paid
services.

## Setup

Needs [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/shubhamwagh/car-health-check
cd car-health-check
uv sync
cp .env.example .env
```

Fill in `.env`:

- `ZYFY_API_KEY`, get one free at https://zyfy.uk/signup
- `MOT_CLIENT_ID`, `MOT_CLIENT_SECRET`, `MOT_API_KEY`, register at
  https://documentation.history.mot.api.gov.uk/mot-history-api/register
  (free, takes 1-3 days for approval)

If the MOT credentials aren't ready yet, the app still works, that section
just shows an error until you fill it in.

## Run

```bash
uv run car-health-check --reload
```

Then open http://127.0.0.1:8000.

## Docker

```bash
docker build -t car-health-check .
docker run -p 8000:8000 --env-file .env car-health-check
```

## Tests

```bash
uv run pytest
```
