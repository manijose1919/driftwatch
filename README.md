# 🛰️ DriftWatch

**Self-hosted API contract drift sentinel.** DriftWatch watches the third-party
JSON APIs your app depends on and alerts you the moment their response
*shape* changes — before your production code finds out the hard way.

It diffs inferred **type-shapes**, never raw data, so changing values never
fire an alarm; only structural drift does:

- 🔴 **breaking** — field removed, type changed, value now always null
- 🟡 **risky** — new enum value, field became nullable/optional, int → float
- 🟢 **benign** — purely additive (new field, array shape learned)

No paid services, no provider cooperation needed, no external database.
One Python process, one SQLite file.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8080
```

Open **http://127.0.0.1:8080/** for the dashboard, `/docs` for the REST API.

### Try it in 60 seconds (built-in demo API)

1. In the dashboard, add an endpoint with URL `http://127.0.0.1:8080/demo/products`.
2. Wait ~5 seconds — the scheduler probes it and captures the baseline shape.
3. Break the demo API: `POST /demo/scenario/1` (price becomes a string, a field disappears).
4. Click **Probe now** → a 🔴 breaking event appears with the exact JSON paths.
5. Click **Accept as new baseline** when a change is intentional.

Scenarios: `0` baseline · `1` breaking · `2` risky · `3` benign.

## How it works

```
schedule ──► probe endpoint ──► infer type-shape ──► diff vs baseline
                                                          │
                 dashboard feed ◄── drift event ◄── classify changes
                 Discord/Slack alert ◄──┘
```

- **Shape inference** (`app/engine/shape.py`): converts a JSON payload into a
  structure-only signature — types, object fields, array item shapes,
  optionality, nullability, and enum candidates (few distinct, repeating,
  short string values).
- **Classifier** (`app/engine/differ.py`): diffs baseline vs current shape
  and assigns each change a severity from the *consumer's* point of view.
  It stops recursing below a type change, so one root cause = one alert line.
- **Prober** (`app/engine/prober.py`): edge-triggered error events (one alert
  when an endpoint starts failing, not one per probe) and duplicate-drift
  suppression (a persisting drift alerts once until accepted/acknowledged).
- **Alerts** (`app/alerts.py`): Discord / Slack / generic webhooks, each with
  its own minimum-severity threshold.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DRIFTWATCH_DB` | `sqlite:///./driftwatch.db` | SQLAlchemy database URL |
| `DRIFTWATCH_API_TOKEN` | *(empty = auth off)* | Bearer token required on `/api/*` |
| `DRIFTWATCH_SCHEDULER_ENABLED` | `true` | Disable to probe manually only |
| `DRIFTWATCH_PROBE_TIMEOUT` | `15` | Per-probe HTTP timeout (seconds) |

When a token is set, the dashboard needs it too — in the browser console:
`localStorage.dw_token = 'your-token'`.

## Docker

```bash
docker build -t driftwatch .
docker run -p 8080:8080 -v driftwatch-data:/data -e DRIFTWATCH_DB=sqlite:////data/driftwatch.db driftwatch
```

## Tests

```powershell
.venv\Scripts\python -m pytest tests -q
```

40 tests cover shape inference, the breaking-change classifier, and the full
probe → drift → alert → accept lifecycle over the REST API.

## Project layout

```
app/
  main.py          FastAPI app: routers, static dashboard, lifespan
  config.py        env-based settings
  database.py      SQLAlchemy engine/session
  models.py        Endpoint, Snapshot, DriftEvent, AlertChannel
  schemas.py       Pydantic request/response models
  auth.py          optional bearer-token guard
  scheduler.py     APScheduler: one interval job per endpoint
  alerts.py        webhook alert dispatcher
  engine/
    shape.py       JSON -> type-shape inference
    differ.py      shape diff + severity classifier
    prober.py      probe executor (fetch, diff, record)
  routes/
    endpoints.py   endpoint CRUD + probe-now + snapshots
    drift.py       drift feed, ack, accept-baseline, stats
    channels.py    alert channel CRUD + webhook test
    demo.py        built-in mutable demo API
static/            zero-build dashboard (vanilla JS SPA)
tests/             pytest suite
```
