"""
Hard constraint: the ledger.jsonl record schema must not change in a way
that breaks the sibling interagent-queue skill, which parses it directly
(Skills/interagent-queue/scripts/interagent_queue.py). New optional keys are
fine; renaming or removing existing ones is not.

This runs interagent_queue.py's `peek` command against a scratch ledger
produced by claw-callback.py to confirm it still parses cleanly.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import CB_SCRIPT, REPO_ROOT, parse_json

IQ_SCRIPT = REPO_ROOT.parent / "interagent-queue" / "scripts" / "interagent_queue.py"


def test_interagent_queue_parses_scratch_ledger(run_cb, claw_home):
    if not IQ_SCRIPT.exists():
        import pytest
        pytest.skip(f"interagent-queue not present at {IQ_SCRIPT}; nothing to cross-check")

    r = run_cb("create", "--task", "cross-skill schema check", "--from", "main",
               "--to", "planner", "--summary", "s")
    assert r.returncode == 0

    env = os.environ.copy()
    env["CLAW_HOME"] = str(claw_home)
    env["LYRA_WORKSPACE"] = str(claw_home / "workspace")

    result = subprocess.run([sys.executable, str(IQ_SCRIPT), "peek"],
                             capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["messages"], "interagent_queue should have rendered at least one event"
    assert "Enqueued Task" in out["messages"][0]


def test_interagent_queue_renders_corrupt_event(run_cb, claw_home):
    """The `corrupt` event (T6) is appended by quarantine_envelope() when list/sweep
    move a bad envelope aside. format_event() must render it rather than silently
    dropping it (returning None) like it does for any other unrecognised event —
    otherwise quarantine notices never reach the Discord-facing log, defeating the
    whole point of quarantining instead of skipping."""
    if not IQ_SCRIPT.exists():
        import pytest
        pytest.skip(f"interagent-queue not present at {IQ_SCRIPT}; nothing to cross-check")

    # Get a real ledger file (and its parent dir) into existence the same way the
    # `create` case above does, then append a hand-built `corrupt` record onto it —
    # this is the exact shape quarantine_envelope() writes.
    r = run_cb("create", "--task", "corrupt-event schema check", "--from", "main",
               "--to", "planner", "--summary", "s")
    assert r.returncode == 0

    ledger = claw_home / "state" / "callbacks" / "ledger.jsonl"
    quarantined_to = claw_home / "state" / "callbacks" / "archive" / "corrupt" / "cb-20260101000000-abc123.json"
    record = {
        "at": "2026-01-01T00:00:00Z",
        "id": "cb-20260101000000-abc123",
        "event": "corrupt",
        "by": "system",
        "reason": "JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
        "quarantined_to": str(quarantined_to),
    }
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    env = os.environ.copy()
    env["CLAW_HOME"] = str(claw_home)
    env["LYRA_WORKSPACE"] = str(claw_home / "workspace")

    result = subprocess.run([sys.executable, str(IQ_SCRIPT), "peek"],
                             capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    rendered = "\n".join(out["messages"])
    assert "cb-20260101000000" in rendered, (
        f"corrupt event was dropped instead of rendered: {out['messages']!r}")
    assert "Quarantined" in rendered
