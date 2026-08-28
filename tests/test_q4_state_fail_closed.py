"""The reader's cursor must never rewind silently (MQ Q4).

miab_observer.py is a cursor over an append-only ledger, so its dangerous
failure is not crashing — it is rewinding. Until 1.3.0, load_state() swallowed
every exception and fell through to the same
`{"enabled": False, "last_processed_line": 0}` default it uses for a genuine
fresh start, so a truncated or malformed queue_state.json rewound the cursor to
0 without a word and the next `process` replayed the ENTIRE ledger into the log.
Duplicated output is harder to notice, and harder to undo, than no output.

That shipped in 1.2.0 and was live in every install from 2026-07-22 until 1.3.0.

The distinction these tests pin: a MISSING state file is a fresh start; a
PRESENT but unusable one is an error that must fail closed.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import IQ_SCRIPT


def _status(claw_home, state_text=None):
    """Run `miab_observer.py status`, optionally seeding queue_state.json first."""
    ws = claw_home / "workspace"
    if state_text is not None:
        d = ws / "state" / "callbacks"
        d.mkdir(parents=True, exist_ok=True)
        (d / "queue_state.json").write_text(state_text, encoding="utf-8")
    env = os.environ.copy()
    env["CLAW_HOME"] = str(claw_home)
    env["LYRA_WORKSPACE"] = str(ws)
    return subprocess.run([sys.executable, str(IQ_SCRIPT), "status"],
                          capture_output=True, text=True, env=env)


def test_missing_state_file_is_a_fresh_start(claw_home):
    """No state file at all is the one case where cursor 0 is the right answer."""
    result = _status(claw_home)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["last_processed_line"] == 0
    assert out["enabled"] is False


def test_intact_state_file_is_honoured(claw_home):
    """Control: a well-formed cursor survives, so the guards below aren't vacuous."""
    result = _status(claw_home, '{"enabled": true, "last_processed_line": 42}')
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["last_processed_line"] == 42
    assert out["enabled"] is True


@pytest.mark.parametrize("state_text, label", [
    ('{"enabled": true, "last_proc', "truncated mid-write"),
    ("", "empty file"),
    ("not json at all", "not json"),
    ("[1, 2, 3]", "json, but not an object"),
    ("null", "json null"),
    ('{"last_processed_line": -5}', "negative cursor"),
    ('{"last_processed_line": "12"}', "cursor is a string"),
    ('{"last_processed_line": 1.5}', "cursor is a float"),
])
def test_unusable_state_file_fails_closed(claw_home, state_text, label):
    """A present-but-unusable state file must exit non-zero, not reset to 0.

    The regression this guards is silent replay, so the assertion that matters is
    that the process refuses — never that it "helpfully" carried on from zero.
    """
    result = _status(claw_home, state_text)
    assert result.returncode == 1, (
        f"{label}: expected exit 1, got {result.returncode}. "
        f"stdout={result.stdout!r}")
    assert result.stdout.strip() == "", (
        f"{label}: refusing to run should print nothing to stdout")
    err = json.loads(result.stderr)
    assert err["ok"] is False
    assert "state_file" in err and "remedy" in err


def test_refusal_does_not_rewrite_the_state_file(claw_home):
    """Failing closed must leave the damaged file intact for the operator.

    If the refusal path also saved state it would destroy the very bytes needed to
    recover the real cursor, turning a recoverable fault into the replay it avoids.
    """
    damaged = '{"enabled": true, "last_proc'
    result = _status(claw_home, damaged)
    assert result.returncode == 1
    on_disk = (claw_home / "workspace" / "state" / "callbacks" /
               "queue_state.json").read_text(encoding="utf-8")
    assert on_disk == damaged, "the damaged state file was overwritten"
