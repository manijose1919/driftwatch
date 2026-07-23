# Contributing to DriftWatch

Thanks for your interest! DriftWatch is a single FastAPI process backed by
SQLite, with a zero-build vanilla-JS dashboard — no Node toolchain, no compile
step. That keeps the contributor loop short.

## Dev setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows (runtime + test/lint tools)
# .venv/bin/pip install -r requirements-dev.txt       # macOS/Linux

# Run the server (any free port)
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8420
```

Runtime dependencies live in `requirements.txt` (pinned; this is all the Docker
image installs); `requirements-dev.txt` adds the test and lint tooling on top.

Open `http://127.0.0.1:8420/` for the dashboard and `/docs` for the OpenAPI UI.
There's a built-in mutable demo API at `/demo/products` for exercising drift
detection without a real third-party endpoint — see the "Try it in 60 seconds"
section of the [README](README.md).

## Running the tests

```bash
.venv/Scripts/python -m pytest tests -q
```

The suite is fast (a couple of seconds) and network-free — the prober's HTTP
call is monkeypatched with canned payloads (see `tests/conftest.py`). Please add
or update tests for any behavior change; CI runs this same suite on every push
and pull request.

## Linting

```bash
.venv/Scripts/ruff check .
```

CI runs `ruff check` (pyflakes + pycodestyle errors) on every push and PR.
Formatting is intentionally *not* auto-enforced — match the style of the code
around your change. Ruff config lives in `pyproject.toml`.

## Conventions

- **Shapes, not data.** The core invariant is that DriftWatch diffs *structure*,
  never values. If you touch `app/engine/`, keep value samples out of the
  signal — an observation consistent with the baseline contract is not drift.
- **Keep it one process.** No new runtime services or build steps without a
  strong reason; single-process self-hosting is a design goal.
- **Match the surrounding style** — standard library + FastAPI/SQLAlchemy
  idioms, type hints, and short docstrings explaining *why*, not *what*.

## Pull requests

1. Fork and branch from `main`.
2. Make the change with tests; run the suite locally.
3. Open a PR with a clear description of the problem and the approach.

Small, focused PRs get reviewed fastest. Thank you for contributing!
