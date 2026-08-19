"""
T12 — depth and cycle guards on `forward`.

Before this, 50 alternating forwards produced a 51-frame, 13 KB envelope with no
complaint, and production logged a `SPECTRE -> SPECTRE` self-forward that the
broker happily recorded. Both are runaway chains, not plans.
"""
import json

from conftest import parse_json


def err(r):
    return parse_json(r.stderr)["error"]


def make(run_cb):
    return parse_json(run_cb("create", "--task", "t", "--from", "main",
                             "--to", "a0", "--summary", "s").stdout)["id"]


def test_self_forward_is_refused(run_cb):
    cid = make(run_cb)
    r = run_cb("forward", "--id", cid, "--from", "a0", "--to", "a0", "--summary", "s")
    assert r.returncode != 0
    assert "cannot forward to itself" in err(r)


def test_self_forward_is_refused_across_casing(run_cb):
    cid = make(run_cb)
    r = run_cb("forward", "--id", cid, "--from", "a0", "--to", "A0", "--summary", "s")
    assert r.returncode != 0
    assert "cannot forward to itself" in err(r)


def test_forward_back_to_an_agent_already_on_the_stack_is_refused(run_cb):
    cid = make(run_cb)                       # stack: [main]
    run_cb("forward", "--id", cid, "--from", "a0", "--to", "a1", "--summary", "s")
    r = run_cb("forward", "--id", cid, "--from", "a1", "--to", "main", "--summary", "s")
    assert r.returncode != 0
    assert "already waiting on this callback" in err(r)


def test_allow_cycle_permits_a_self_forward(run_cb):
    cid = make(run_cb)
    r = run_cb("forward", "--id", cid, "--from", "a0", "--to", "a0",
               "--summary", "s", "--allow-cycle")
    assert r.returncode == 0, r.stderr


def test_depth_is_capped_at_max_stack_depth(run_cb, claw_home):
    cid = make(run_cb)                       # 1 frame on the stack
    for i in range(7):                       # -> 8 frames
        r = run_cb("forward", "--id", cid, "--from", f"a{i}", "--to", f"a{i+1}", "--summary", "s")
        assert r.returncode == 0, f"forward {i}: {r.stderr}"
    env = json.loads((claw_home / "state" / "callbacks" / f"{cid}.json").read_text())
    assert len(env["stack"]) == 8
    r = run_cb("forward", "--id", cid, "--from", "a7", "--to", "a8", "--summary", "s")
    assert r.returncode != 0
    assert "MAX_STACK_DEPTH=8" in err(r)


def test_allow_cycle_permits_exceeding_the_depth_cap(run_cb):
    cid = make(run_cb)
    for i in range(7):
        run_cb("forward", "--id", cid, "--from", f"a{i}", "--to", f"a{i+1}", "--summary", "s")
    r = run_cb("forward", "--id", cid, "--from", "a7", "--to", "a8",
               "--summary", "s", "--allow-cycle")
    assert r.returncode == 0, r.stderr


def test_a_refused_forward_leaves_the_envelope_untouched(run_cb, claw_home):
    cid = make(run_cb)
    before = (claw_home / "state" / "callbacks" / f"{cid}.json").read_text()
    run_cb("forward", "--id", cid, "--from", "a0", "--to", "a0", "--summary", "s")
    assert (claw_home / "state" / "callbacks" / f"{cid}.json").read_text() == before
