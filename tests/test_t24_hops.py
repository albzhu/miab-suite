"""
T24 — `hops` has one definition: delegation edges traversed (the `create` plus
every `forward`). Before this fix three contradictory definitions coexisted —
`len(env["results"])` in the CLI's resolve event, `len(bottle_records)` in the
retired notifier path, and nothing in the envelope. The envelope now carries the
counter; pre-2.1.0 envelopes derive it from history.
"""
import json
from conftest import parse_json


def _register_all(run_cb):
    for agent, agent_id in [("main", "agent:main"), ("planner", "agent:planner"),
                            ("coder", "agent:coder")]:
        assert run_cb("register", "--agent", agent, "--agent-id", agent_id).returncode == 0


def _resolve_event(claw_home, cid):
    lines = (claw_home / "state" / "callbacks" / "ledger.jsonl").read_text().splitlines()
    evs = [json.loads(l) for l in lines]
    return next(e for e in evs if e["id"] == cid and e["event"] == "resolve")


def _envelope(claw_home, cid):
    return json.loads((claw_home / "state" / "callbacks" / f"{cid}.json").read_text())


def test_single_hop_chain_records_hops_1(run_cb, claw_home):
    """create -> return -> resolve --result is ONE hop, even though results holds
    two entries by resolve time (the old len(results) definition said 2)."""
    _register_all(run_cb)
    cid = parse_json(run_cb("create", "--task", "t", "--from", "main", "--to", "planner",
                            "--summary", "s").stdout)["id"]
    assert _envelope(claw_home, cid)["hops"] == 1
    assert run_cb("return", "--id", cid, "--from", "planner", "--result", "done").returncode == 0
    assert run_cb("resolve", "--id", cid, "--from", "main", "--result", "wrapped").returncode == 0
    assert _resolve_event(claw_home, cid)["hops"] == 1


def test_each_forward_adds_a_hop(run_cb, claw_home):
    _register_all(run_cb)
    cid = parse_json(run_cb("create", "--task", "t", "--from", "main", "--to", "planner",
                            "--summary", "s").stdout)["id"]
    run_cb("forward", "--id", cid, "--from", "planner", "--to", "coder", "--summary", "s2")
    assert _envelope(claw_home, cid)["hops"] == 2
    run_cb("return", "--id", cid, "--from", "coder", "--result", "r1")
    run_cb("return", "--id", cid, "--from", "planner", "--result", "r2")
    assert run_cb("resolve", "--id", cid, "--from", "main").returncode == 0
    assert _resolve_event(claw_home, cid)["hops"] == 2


def test_pre_2_1_0_envelope_derives_hops_from_history(run_cb, claw_home):
    """An envelope written before the counter existed still resolves with the right
    count: history carries exactly one line per create/forward."""
    _register_all(run_cb)
    cid = parse_json(run_cb("create", "--task", "t", "--from", "main", "--to", "planner",
                            "--summary", "s").stdout)["id"]
    ep = claw_home / "state" / "callbacks" / f"{cid}.json"
    env = json.loads(ep.read_text())
    del env["hops"]                          # simulate a pre-2.1.0 envelope
    ep.write_text(json.dumps(env))
    run_cb("forward", "--id", cid, "--from", "planner", "--to", "coder", "--summary", "s2")
    assert _envelope(claw_home, cid)["hops"] == 2   # derived (1) + this forward
    run_cb("return", "--id", cid, "--from", "coder", "--result", "r1")
    run_cb("return", "--id", cid, "--from", "planner", "--result", "r2")
    run_cb("resolve", "--id", cid, "--from", "main")
    assert _resolve_event(claw_home, cid)["hops"] == 2
