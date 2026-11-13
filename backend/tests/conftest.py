"""Every assistant test stores reports in a fresh temporary folder, never in Supabase or outputs/."""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    yield


@pytest.fixture(autouse=True)
def _scenarios_treated_as_current(monkeypatch):
    """Tests of the advisory engine use the published crop outlook as it is; whether its scenarios.json matches the
    current crop configuration depends on the day's data, so it is treated as current here. The guard itself is
    tested with the real check (test_advisory: REAL_SCENARIOS_CURRENT)."""
    from assistant import advisory
    monkeypatch.setattr(advisory, "scenarios_current", lambda scen, run: True)
    yield
