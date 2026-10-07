"""The notifier tests must never be able to run the real `openclaw`.

`notify_closed_bottles.py` shells out to `openclaw message send`, so a test that let that
lookup fall through to a real install would post fixture data to a real chat channel. The
`notifier` fixture (tests/conftest.py) is built so it cannot, and these tests pin how.
"""
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import NOTIFY_SCRIPT, SYNTHETIC_TARGET, make_bottle


def test_the_only_openclaw_on_path_is_the_fake_under_tmp_path(notifier, monkeypatch, tmp_path):
    # A developer's real configuration must not leak into a run.
    monkeypatch.setenv("CLAW_CLOSED_TARGET", "channel:999999999999999999")
    monkeypatch.setenv("CLAW_CLOSED_STATE", "/nonexistent/ambient-state.json")
    monkeypatch.setenv("CLAW_LEDGER", "/nonexistent/ambient-ledger.jsonl")
    monkeypatch.setenv("CLAW_CLOSED_ACCOUNT", "ambient-account")

    env = notifier.env()
    assert env["PATH"] == str(notifier.bin_dir), "PATH must hold the fake and nothing else"
    assert tmp_path in notifier.bin_dir.parents
    found = shutil.which("openclaw", path=env["PATH"])
    assert found is not None and Path(found).parent == notifier.bin_dir

    assert env["CLAW_CLOSED_TARGET"] == SYNTHETIC_TARGET
    for leaked in ("CLAW_CLOSED_STATE", "CLAW_LEDGER", "CLAW_CLOSED_ACCOUNT"):
        assert leaked not in env
    assert env["CLAW_HOME"] == str(notifier.claw_home)
    assert env["HOME"] == str(notifier.home)


def test_with_the_fake_gone_a_delivery_fails_rather_than_finding_a_real_cli(notifier):
    """There is no second PATH entry for a real `openclaw` to be found on, so removing the
    fake makes the send fail, and the cursor parks on that bottle for the next run."""
    notifier.write_ledger(make_bottle("cb-20260101000000-aaa001", "resolve"))
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": []})
    env = notifier.env()                       # asserts the fake is first on PATH, then...
    (notifier.bin_dir / "openclaw").unlink()   # ...takes it away

    r = subprocess.run([sys.executable, str(NOTIFY_SCRIPT), "process"], env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=notifier.tmp_path, timeout=60)
    assert "delivery failed" in r.stderr, r.stderr
    assert notifier.calls() == []
    assert notifier.state()["last_processed_line"] == 2
    assert notifier.state()["delivered_ids"] == []
