"""crop_engine.run_all's wall-clock time limit (run_until): a child past the deadline is stopped with what it started."""
import os
import sys
import time

from crop_engine import run_all


def test_child_ending_before_the_deadline_gives_its_exit_code(monkeypatch):
    monkeypatch.setattr(run_all, "POLL", 0.2)
    assert run_until_code([sys.executable, "-c", "import sys; sys.exit(3)"], time.time() + 30) == 3
    assert run_until_code([sys.executable, "-c", "pass"], None) == 0


def test_child_past_the_wall_clock_deadline_is_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(run_all, "POLL", 0.2)
    flag = (tmp_path / "still_running").as_posix()
    # the child starts a grandchild that would write the flag after 4 s: stopping the child must stop it too
    code = ("import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4); open(\"{flag}\", \"w\").write(\"x\")']); "
            "time.sleep(30)")
    t0 = time.time()
    assert run_until_code([sys.executable, "-c", code], time.time() + 1) is None
    assert time.time() - t0 < 10
    time.sleep(5)
    assert not os.path.exists(flag)


def test_a_deadline_already_past_stops_the_child_at_the_first_check(monkeypatch):
    """After a sleep or standby the deadline may be long past: the child is stopped at once."""
    monkeypatch.setattr(run_all, "POLL", 0.2)
    t0 = time.time()
    assert run_until_code([sys.executable, "-c", "import time; time.sleep(30)"], time.time() - 3600) is None
    assert time.time() - t0 < 5


def run_until_code(cmd, end):
    return run_all.run_until(cmd, None, end)
