"""Every assistant test stores reports in a fresh temporary folder, never in Supabase or outputs/."""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    yield
