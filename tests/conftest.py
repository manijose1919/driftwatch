"""Test bootstrap: must configure env BEFORE importing app modules."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="driftwatch-tests-")
os.environ["DRIFTWATCH_SCHEDULER_ENABLED"] = "0"
os.environ["DRIFTWATCH_DB"] = "sqlite:///" + os.path.join(_tmp, "test.db").replace("\\", "/")
os.environ["DRIFTWATCH_API_TOKEN"] = ""
# Single-probe baselines by default; learning-phase tests override in-test.
os.environ["DRIFTWATCH_BASELINE_PROBES"] = "1"
os.environ["DRIFTWATCH_PROBE_BACKOFF"] = "0"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake_api(monkeypatch):
    """Replace the prober's network call with a controllable canned payload."""
    from app.engine import prober

    state = {"payload": {}, "error": None}

    async def _fake_request(endpoint):
        if state["error"] is not None:
            raise prober.ProbeError(state["error"])
        return state["payload"], 200, 1.23

    monkeypatch.setattr(prober, "_request", _fake_request)
    return state
