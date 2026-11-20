"""scripts/publish_daily.py: the push has a time limit, and a push the server took counts as published."""
import importlib.util
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("publish_daily", ROOT / "scripts" / "publish_daily.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


def _run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repos(tmp_path):
    """A bare origin and a clone with one commit on main, pushed."""
    origin, wt = tmp_path / "origin.git", tmp_path / "wt"
    _run("init", "--quiet", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _run("clone", "--quiet", str(origin), str(wt), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@example.org")):
        _run("config", k, v, cwd=wt)
    _run("checkout", "--quiet", "-b", "main", cwd=wt)
    (wt / "a.txt").write_text("1", encoding="utf-8")
    _run("add", "a.txt", cwd=wt)
    _run("commit", "--quiet", "-m", "one", cwd=wt)
    _run("push", "--quiet", "origin", "HEAD:main", cwd=wt)
    return origin, wt


def _commit(wt, text):
    (wt / "a.txt").write_text(text, encoding="utf-8")
    _run("commit", "--quiet", "-am", text, cwd=wt)


def test_push_sends_the_commit(tmp_path):
    _, wt = _repos(tmp_path)
    _commit(wt, "2")
    assert publish.push(cwd=wt).returncode == 0
    assert publish.on_origin(cwd=wt)


def test_a_hung_git_is_stopped_at_the_time_limit(tmp_path):
    _, wt = _repos(tmp_path)
    hook = wt / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
    hook.chmod(0o755)
    _commit(wt, "2")
    t0 = time.monotonic()
    r = publish.git("push", "--quiet", "origin", "HEAD:main", cwd=wt, check=False, timeout=3)
    assert time.monotonic() - t0 < 30
    assert r.returncode == 124 and "timed out" in r.stderr
    assert not publish.on_origin(cwd=wt)                    # the hook held it before anything was sent


def test_a_commit_already_on_origin_counts_as_pushed(tmp_path):
    origin, wt = _repos(tmp_path)
    _commit(wt, "2")
    _run("push", "--quiet", "origin", "HEAD:main", cwd=wt)  # the server took it, whatever the client heard
    assert publish.on_origin(cwd=wt)
    _commit(wt, "3")                                        # a commit the server does not have
    assert not publish.on_origin(cwd=wt)
