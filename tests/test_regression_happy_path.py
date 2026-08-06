"""
Regression: the documented workflows must still work end to end after M1's
hardening. No task's fix should break the happy path.
"""
from conftest import parse_json


def _register_all(run_cb):
    for agent, agent_id in [("main", "agent:main"), ("planner", "agent:planner"),
                             ("coder", "agent:coder")]:
        r = run_cb("register", "--agent", agent, "--agent-id", agent_id)
        assert r.returncode == 0


def test_simple_chain_create_wake_return_resolve(run_cb):
    _register_all(run_cb)

    r = run_cb("create", "--task", "t1", "--from", "main", "--to", "planner", "--summary", "s1")
    assert r.returncode == 0
    cid = parse_json(r.stdout)["id"]

    r = run_cb("wake", "--id", cid)
    assert r.returncode == 0
    assert parse_json(r.stdout)["ok"] is True

    r = run_cb("return", "--id", cid, "--from", "planner", "--result", "done1")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["terminal"] is True
    assert out["wake"] == "main"

    r = run_cb("resolve", "--id", cid, "--from", "main")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["status"] == "resolved"
    assert out["cleaned_up"] is True


def test_forward_chain_create_forward_return_return_resolve(run_cb):
    _register_all(run_cb)

    r = run_cb("create", "--task", "t2", "--from", "main", "--to", "planner", "--summary", "s2")
    cid = parse_json(r.stdout)["id"]

    r = run_cb("forward", "--id", cid, "--from", "planner", "--to", "coder", "--summary", "s3")
    assert r.returncode == 0
    assert parse_json(r.stdout)["stack_depth"] == 2

    r = run_cb("return", "--id", cid, "--from", "coder", "--result", "coder-done")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["terminal"] is False
    assert out["wake"] == "planner"

    r = run_cb("return", "--id", cid, "--from", "planner", "--result", "planner-done")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["terminal"] is True
    assert out["wake"] == "main"
    assert len(out["results_so_far"]) == 2

    r = run_cb("resolve", "--id", cid, "--from", "main")
    assert r.returncode == 0
    assert parse_json(r.stdout)["status"] == "resolved"


def test_list_and_sweep_after_full_cycle_are_clean(run_cb):
    _register_all(run_cb)
    r = run_cb("create", "--task", "t", "--from", "main", "--to", "planner", "--summary", "s")
    cid = parse_json(r.stdout)["id"]
    run_cb("return", "--id", cid, "--from", "planner", "--result", "done")
    run_cb("resolve", "--id", cid, "--from", "main")

    r = run_cb("list")
    assert r.returncode == 0
    assert "No active callbacks." in r.stdout

    r = run_cb("sweep", "--older-than", "0")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["stale_count"] == 0
    assert out["quarantined"] == 0
