"""
T22 — `register --session-key` and the wake-route it selects.

A registry entry may carry an exact `sessionKey` that overrides the agent's
default wake lane, so a bottle completion resurfaces in a specific chat session
rather than the agent's background lane. Entries without one must keep emitting
the `cron(action=wake, agentId=…)` instruction unchanged — this is additive.
"""
import json

from conftest import parse_json


def _create(run_cb, frm="main", to="planner"):
    r = run_cb("create", "--task", "t", "--from", frm, "--to", to, "--summary", "s")
    assert r.returncode == 0, r.stderr
    return parse_json(r.stdout)["id"]


def test_register_without_session_key_routes_via_cron(run_cb):
    r = run_cb("register", "--agent", "planner", "--agent-id", "agent:planner")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["ok"] is True
    assert "sessionKey" not in out
    assert "action=wake, agentId='agent:planner'" in out["next_step"]
    assert "sessions_send" not in out["next_step"]


def test_register_with_session_key_routes_via_sessions_send(run_cb):
    r = run_cb("register", "--agent", "main", "--agent-id", "agent:main",
               "--session-key", "agent:main:chat:session:xyz")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["sessionKey"] == "agent:main:chat:session:xyz"
    assert "sessions_send(sessionKey='agent:main:chat:session:xyz')" in out["next_step"]


def test_session_key_persists_into_the_registry(run_cb, claw_home):
    run_cb("register", "--agent", "main", "--agent-id", "agent:main",
           "--session-key", "agent:main:chat:session:xyz")
    reg = json.loads((claw_home / "state" / "callbacks" / "agent-registry.json").read_text())
    assert reg["agents"]["main"]["sessionKey"] == "agent:main:chat:session:xyz"


def test_wake_prefers_session_key_over_agent_id(run_cb):
    run_cb("register", "--agent", "planner", "--agent-id", "agent:planner",
           "--session-key", "agent:planner:chat:session:abc")
    cid = _create(run_cb)
    r = run_cb("wake", "--id", cid, "--to", "planner")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["sessionKey"] == "agent:planner:chat:session:abc"
    assert out["agentId"] == "agent:planner"          # still reported, not replaced
    assert "sessions_send(sessionKey='agent:planner:chat:session:abc'" in out["next_step"]
    assert "message=<dispatch_message above>" in out["next_step"]
    assert "cron(action=wake" not in out["next_step"]


def test_wake_without_session_key_is_unchanged(run_cb):
    run_cb("register", "--agent", "planner", "--agent-id", "agent:planner")
    cid = _create(run_cb)
    r = run_cb("wake", "--id", cid, "--to", "planner")
    out = parse_json(r.stdout)
    assert "sessionKey" not in out
    assert "action=wake, agentId='agent:planner'" in out["next_step"]
    assert "sessions_send" not in out["next_step"]


def test_return_emits_wake_session_key_for_the_woken_agent(run_cb):
    run_cb("register", "--agent", "main", "--agent-id", "agent:main",
           "--session-key", "agent:main:chat:session:xyz")
    cid = _create(run_cb)
    r = run_cb("return", "--id", cid, "--from", "planner", "--result", "done")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["wake"] == "main"
    assert out["wake_sessionKey"] == "agent:main:chat:session:xyz"
    assert "sessions_send(sessionKey='agent:main:chat:session:xyz'" in out["next_step"]


def test_return_without_session_key_is_unchanged(run_cb):
    run_cb("register", "--agent", "main", "--agent-id", "agent:main")
    cid = _create(run_cb)
    r = run_cb("return", "--id", cid, "--from", "planner", "--result", "done")
    out = parse_json(r.stdout)
    assert "wake_sessionKey" not in out
    assert "action=wake, agentId='agent:main'" in out["next_step"]
    assert "sessions_send" not in out["next_step"]
