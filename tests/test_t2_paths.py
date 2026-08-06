"""
T2 — every emitted command path must be runnable verbatim from any cwd. [F1]

Regression guard: `create`/`wake_message` used to emit a CWD-relative path
(`Skills/miab-broker/scripts/bin/claw-callback.py`), and the `wake` fallback
and SKILL.md examples both omitted `bin/`. An agent following `next_step`
from anywhere but the repo root got "No such file or directory".
"""
import re

from conftest import CB_SCRIPT, parse_json


CMD_RE = re.compile(r"`([^`]*claw-callback\.py[^`]*)`")


def _extract_backticked_commands(text: str):
    return CMD_RE.findall(text)


def test_create_next_step_command_runs_from_other_cwd(run_cb, tmp_path):
    r = run_cb("create", "--task", "t", "--from", "main", "--to", "planner", "--summary", "s")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    cmds = _extract_backticked_commands(out["next_step"])
    assert cmds, "expected a backticked claw-callback.py command in next_step"

    other_cwd = tmp_path / "somewhere_else"
    other_cwd.mkdir()
    # Run the extracted command from a directory that has no relative access
    # to the script at all — it must still resolve.
    import os
    import subprocess
    env = os.environ.copy()
    env["CLAW_HOME"] = env.get("CLAW_HOME", "")
    result = subprocess.run(["bash", "-c", cmds[0]], cwd=other_cwd,
                             capture_output=True, text=True,
                             env={**os.environ, "CLAW_HOME": str(tmp_path / "unused_home")})
    assert "No such file or directory" not in result.stderr
    assert str(CB_SCRIPT) in cmds[0]


def test_wake_message_paths_are_absolute(run_cb):
    r = run_cb("create", "--task", "t", "--from", "main", "--to", "planner", "--summary", "s")
    cid = parse_json(r.stdout)["id"]

    r2 = run_cb("wake", "--id", cid)
    out = parse_json(r2.stdout)
    assert str(CB_SCRIPT) in out["dispatch_message"]
    assert "~/.openclaw/scripts/claw-callback.py" not in out["dispatch_message"]
    # The old bug emitted a bare CWD-relative path; the fix must emit the full
    # absolute path instead, so "python3 Skills/..." (no absolute prefix) must
    # never appear even though the correct absolute path legitimately ends
    # with that same suffix.
    assert "python3 Skills/miab-broker" not in out["dispatch_message"]


def test_return_dispatch_message_paths_are_absolute(run_cb):
    r = run_cb("create", "--task", "t", "--from", "main", "--to", "planner", "--summary", "s")
    cid = parse_json(r.stdout)["id"]

    r2 = run_cb("return", "--id", cid, "--from", "planner", "--result", "done")
    out = parse_json(r2.stdout)
    assert str(CB_SCRIPT) in out["dispatch_message"]
    assert "python3 Skills/miab-broker" not in out["dispatch_message"]
