"""
T15 — authority enforcement on --from.

Reproduces the live violation in `cb-20260817223001-cbbb40` (2026-08-17):

    create   by main  -> coder
    forward  by coder -> echo
    return   by echo  -> wake coder
    return   by coder -> wake main
    resolve  by echo                  <- createdBy is main

Two frames popped for one review, and a bottle resolved by an agent that neither
created it nor held it. Nothing was rejected. Six of 46 production bottles carry
a violation of this shape.
"""
import json

from conftest import parse_json


def err(r):
    return parse_json(r.stderr)["error"]


def ledger_events(claw_home, cid=None):
    p = claw_home / "state" / "callbacks" / "ledger.jsonl"
    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return [r for r in recs if cid is None or r.get("id") == cid]


def make(run_cb, frm="main", to="coder"):
    r = run_cb("create", "--task", "t", "--from", frm, "--to", to, "--summary", "s")
    assert r.returncode == 0, r.stderr
    return parse_json(r.stdout)["id"]


# --------------------------------------------------------------------- the live case
def test_the_cbbb40_chain_is_now_rejected_at_the_final_resolve(run_cb):
    cid = make(run_cb, "main", "coder")
    assert run_cb("forward", "--id", cid, "--from", "coder", "--to", "reviewer",
                  "--summary", "review it").returncode == 0
    assert run_cb("return", "--id", cid, "--from", "reviewer", "--result", "lgtm").returncode == 0
    assert run_cb("return", "--id", cid, "--from", "coder", "--result", "done").returncode == 0
    bad = run_cb("resolve", "--id", cid, "--from", "reviewer")
    assert bad.returncode != 0
    assert "is not the originator" in err(bad)
    assert run_cb("resolve", "--id", cid, "--from", "main").returncode == 0


# ------------------------------------------------------------------------- forward
def test_forward_by_a_non_holder_is_refused(run_cb):
    cid = make(run_cb, "main", "coder")
    r = run_cb("forward", "--id", cid, "--from", "main", "--to", "reviewer", "--summary", "s")
    assert r.returncode != 0
    assert "is not the current holder" in err(r)


def test_forward_by_the_holder_is_allowed(run_cb):
    cid = make(run_cb, "main", "coder")
    assert run_cb("forward", "--id", cid, "--from", "coder", "--to", "reviewer",
                  "--summary", "s").returncode == 0


# -------------------------------------------------------------------------- return
def test_return_by_a_non_holder_is_refused(run_cb):
    cid = make(run_cb, "main", "coder")
    r = run_cb("return", "--id", cid, "--from", "reviewer", "--result", "x")
    assert r.returncode != 0
    assert "is not the current holder" in err(r)


# ------------------------------------------------------------------------- resolve
def test_resolve_by_a_non_originator_is_refused(run_cb):
    cid = make(run_cb, "main", "coder")
    run_cb("return", "--id", cid, "--from", "coder", "--result", "done")
    r = run_cb("resolve", "--id", cid, "--from", "coder")
    assert r.returncode != 0
    assert "is not the originator" in err(r)


def test_resolve_with_a_non_empty_stack_is_refused(run_cb):
    """`create -> resolve` with nobody having returned. Four production bottles did
    this; each one silently stranded whoever was still holding the work."""
    cid = make(run_cb, "main", "coder")
    r = run_cb("resolve", "--id", cid, "--from", "main")
    assert r.returncode != 0
    assert "still has 1 frame(s) on the stack" in err(r)


def test_resolve_after_a_full_unwind_is_allowed(run_cb):
    cid = make(run_cb, "main", "coder")
    run_cb("return", "--id", cid, "--from", "coder", "--result", "done")
    assert run_cb("resolve", "--id", cid, "--from", "main").returncode == 0


# -------------------------------------------------------------------------- cancel
def test_cancel_by_a_non_originator_is_refused(run_cb):
    cid = make(run_cb, "main", "coder")
    r = run_cb("cancel", "--id", cid, "--from", "coder", "--reason", "nope")
    assert r.returncode != 0
    assert "is not the originator" in err(r)


def test_cancel_by_the_originator_is_allowed(run_cb):
    cid = make(run_cb, "main", "coder")
    assert run_cb("cancel", "--id", cid, "--from", "main", "--reason", "ok").returncode == 0


# --------------------------------------------------------------- canonical identity
def test_authority_compares_canonical_names(run_cb):
    """An agent that returns as `ECHO` when the envelope says `reviewer` is the same
    agent; rejecting that would be a regression, not a control."""
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer", "--alias", "ECHO")
    cid = make(run_cb, "main", "reviewer")
    assert run_cb("return", "--id", cid, "--from", "REVIEWER", "--result", "x").returncode == 0
    assert run_cb("resolve", "--id", cid, "--from", "Main").returncode == 0


# ---------------------------------------------------------------------- --force
def test_force_permits_the_call_and_records_an_override(run_cb, claw_home):
    cid = make(run_cb, "main", "coder")
    run_cb("return", "--id", cid, "--from", "coder", "--result", "done")
    r = run_cb("resolve", "--id", cid, "--from", "reviewer", "--force")
    assert r.returncode == 0, r.stderr
    ovr = [e for e in ledger_events(claw_home, cid) if e["event"] == "authority-override"]
    assert len(ovr) == 1
    assert ovr[0]["by"] == "reviewer"
    assert ovr[0]["action"] == "resolve"
    assert ovr[0]["expected"] == "main"


def test_force_on_a_non_empty_stack_records_the_remaining_frames(run_cb, claw_home):
    cid = make(run_cb, "main", "coder")
    assert run_cb("resolve", "--id", cid, "--from", "main", "--force").returncode == 0
    ovr = [e for e in ledger_events(claw_home, cid) if e["event"] == "authority-override"]
    assert len(ovr) == 1
    assert ovr[0]["stack_remaining"] == 1


def test_forward_force_records_the_override(run_cb, claw_home):
    cid = make(run_cb, "main", "coder")
    assert run_cb("forward", "--id", cid, "--from", "main", "--to", "reviewer",
                  "--summary", "s", "--force").returncode == 0
    ovr = [e for e in ledger_events(claw_home, cid) if e["event"] == "authority-override"]
    assert ovr[0]["action"] == "forward"
    assert ovr[0]["expected"] == "coder"


def test_an_authorised_call_records_no_override(run_cb, claw_home):
    cid = make(run_cb, "main", "coder")
    run_cb("return", "--id", cid, "--from", "coder", "--result", "done")
    run_cb("resolve", "--id", cid, "--from", "main")
    assert not [e for e in ledger_events(claw_home, cid) if e["event"] == "authority-override"]
