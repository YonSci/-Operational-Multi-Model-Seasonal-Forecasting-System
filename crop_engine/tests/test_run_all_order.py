"""crop_engine.run_all: the gridded regional outlook runs right after the seasonal source, before the weather-model
runs, and not when the seasonal source failed. python -m pytest crop_engine/tests"""
import json
import subprocess
import sys
import types

from crop_engine import run_all


def _run(monkeypatch, sources, fail=()):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--list-sources" in cmd:
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(sources) + "\n", stderr="")
        src = cmd[cmd.index("--sources") + 1] if "--sources" in cmd else None
        return types.SimpleNamespace(returncode=1 if src in fail else 0, stdout="", stderr="")

    def fake_until(cmd, env, end):
        return fake_run(cmd).returncode

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(run_all, "run_until", fake_until)
    monkeypatch.setattr(run_all.dashboard, "write_index", lambda: None)
    monkeypatch.setattr(run_all.dashboard, "write", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_all", "--minutes", "240"])
    run_all.main()
    steps = []
    for c in calls[1:]:
        steps.append(c[c.index("--sources") + 1] if "--sources" in c else c[c.index("-m") + 1])
    return steps


def test_grid_runs_right_after_the_seasonal_source(monkeypatch):
    steps = _run(monkeypatch, ["seasonal", "mr-gfs_global", "s2s-ecmwf"])
    assert steps[:3] == ["seasonal", "crop_engine.grid", "mr-gfs_global"]
    assert steps.count("crop_engine.grid") == 1


def test_no_grid_when_the_seasonal_source_failed(monkeypatch):
    steps = _run(monkeypatch, ["seasonal", "mr-gfs_global"], fail=("seasonal",))
    assert "crop_engine.grid" not in steps
