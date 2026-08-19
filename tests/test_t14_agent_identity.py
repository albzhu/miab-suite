"""
T14 — agent identity: aliases, case-insensitive canonical names, agentId validation.

Live evidence this closes: the registry accumulated `ECHO` as a *second* entry
pointing at `agent:reviewer` alongside `reviewer`, and a forward addressed to
lowercase `echo` still missed both (exact-match lookup), falling to the
unregistered-agent path. `spectre` was registered with `agentId: "planner"` —
a logical name in the routing-id slot, which routes nowhere.
"""
import json

import pytest

from conftest import parse_json


def registry(claw_home):
    return json.loads((claw_home / "state" / "callbacks" / "agent-registry.json").read_text())


def test_registry_key_is_canonicalised(run_cb, claw_home):
    run_cb("register", "--agent", "ECHO", "--agent-id", "agent:reviewer")
    assert "echo" in registry(claw_home)["agents"]
    assert "ECHO" not in registry(claw_home)["agents"]


@pytest.mark.parametrize("spelling", ["reviewer", "REVIEWER", "Reviewer", "  reviewer  "])
def test_lookup_is_case_and_whitespace_insensitive(run_cb, spelling):
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer")
    cid = parse_json(run_cb("create", "--task", "t", "--from", "main",
                            "--to", "reviewer", "--summary", "s").stdout)["id"]
    r = run_cb("wake", "--id", cid, "--to", spelling)
    assert r.returncode == 0, r.stderr
    assert parse_json(r.stdout)["agentId"] == "agent:reviewer"


def test_alias_resolves_to_the_owning_agent(run_cb):
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer", "--alias", "ECHO")
    cid = parse_json(run_cb("create", "--task", "t", "--from", "main",
                            "--to", "reviewer", "--summary", "s").stdout)["id"]
    for spelling in ("ECHO", "echo", "Echo"):
        r = run_cb("wake", "--id", cid, "--to", spelling)
        assert r.returncode == 0, f"{spelling}: {r.stderr}"
        out = parse_json(r.stdout)
        assert out["agentId"] == "agent:reviewer"
        assert out["wake_agent"] == "reviewer"          # canonical, not the alias
        assert out["requested_agent"] == spelling       # what the caller actually said


def test_alias_is_stored_canonically(run_cb, claw_home):
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer",
           "--alias", "ECHO", "--alias", "Echo")
    assert registry(claw_home)["agents"]["reviewer"]["aliases"] == ["echo"]


def test_registering_over_a_legacy_cased_duplicate_merges_it(run_cb, claw_home):
    """The live registry was written by the pre-T14 CLI and holds an `ECHO` key
    verbatim. Re-registering under the canonical name must fold it in, not add a
    third entry."""
    d = claw_home / "state" / "callbacks"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent-registry.json").write_text(json.dumps({
        "version": 1,
        "agents": {"ECHO": {"agentId": "agent:reviewer",
                            "description": "the old duplicate entry"}},
    }))
    r = run_cb("register", "--agent", "echo", "--agent-id", "agent:reviewer")
    assert r.returncode == 0, r.stderr
    agents = registry(claw_home)["agents"]
    assert [k for k in agents if k.casefold() == "echo"] == ["echo"]
    assert agents["echo"]["description"] == "the old duplicate entry"   # not lost
    assert any("merged duplicate" in w for w in parse_json(r.stdout)["warnings"])


def test_legacy_cased_key_still_resolves_before_migration(run_cb, claw_home):
    """Until an operator re-registers, an un-migrated `ECHO` key must still be
    reachable as `echo` — otherwise T14 breaks the very routing it fixes."""
    d = claw_home / "state" / "callbacks"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent-registry.json").write_text(json.dumps({
        "version": 1, "agents": {"ECHO": {"agentId": "agent:reviewer"}}}))
    cid = parse_json(run_cb("create", "--task", "t", "--from", "main",
                            "--to", "reviewer", "--summary", "s").stdout)["id"]
    r = run_cb("wake", "--id", cid, "--to", "echo")
    assert r.returncode == 0, r.stderr
    assert parse_json(r.stdout)["agentId"] == "agent:reviewer"


def test_alias_cannot_shadow_another_agents_own_name(run_cb):
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer")
    r = run_cb("register", "--agent", "coder", "--agent-id", "agent:coder", "--alias", "reviewer")
    assert r.returncode != 0
    assert "already a registered agent" in parse_json(r.stderr)["error"]


def test_alias_cannot_point_at_two_agents(run_cb):
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer", "--alias", "ECHO")
    r = run_cb("register", "--agent", "coder", "--agent-id", "agent:coder", "--alias", "echo")
    assert r.returncode != 0
    assert "already resolves to agent 'reviewer'" in parse_json(r.stderr)["error"]


def test_malformed_agent_id_warns_but_still_registers(run_cb, claw_home):
    """`spectre` is live in production with agentId 'planner'. Refusing would strand it."""
    r = run_cb("register", "--agent", "spectre", "--agent-id", "planner")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert any("does not look like a routing id" in w for w in out["warnings"])
    assert registry(claw_home)["agents"]["spectre"]["agentId"] == "planner"


def test_well_formed_agent_id_does_not_warn(run_cb):
    out = parse_json(run_cb("register", "--agent", "main", "--agent-id", "agent:main").stdout)
    assert "warnings" not in out


def test_display_name_is_stored_for_the_observer(run_cb, claw_home):
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer",
           "--display-name", "ECHO (Reviewer)")
    assert registry(claw_home)["agents"]["reviewer"]["displayName"] == "ECHO (Reviewer)"


def test_envelope_records_canonical_names(run_cb, claw_home):
    cid = parse_json(run_cb("create", "--task", "t", "--from", "MAIN",
                            "--to", "Reviewer", "--summary", "s").stdout)["id"]
    env = json.loads((claw_home / "state" / "callbacks" / f"{cid}.json").read_text())
    assert env["createdBy"] == "main"
    assert env["holder"] == "reviewer"
    assert env["stack"][0]["agent"] == "main"


def test_alias_absorbs_a_duplicate_entry_with_the_same_agent_id(run_cb, claw_home):
    """The live registry holds `ECHO` and `reviewer` as two entries with the same
    agentId, each free to drift. `--alias` collapses them."""
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer")
    run_cb("register", "--agent", "swift", "--agent-id", "agent:reviewer",
           "--description", "kept from the duplicate")
    r = run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer",
               "--alias", "swift")
    assert r.returncode == 0, r.stderr
    agents = registry(claw_home)["agents"]
    assert "swift" not in agents
    assert agents["reviewer"]["aliases"] == ["swift"]
    assert agents["reviewer"]["description"] == "kept from the duplicate"
    assert any("absorbed duplicate agent" in w for w in parse_json(r.stdout)["warnings"])


def test_alias_refuses_to_absorb_an_entry_with_a_different_agent_id(run_cb):
    """`spectre` is registered with agentId 'planner' while `planner` has
    'agent:planner'. Silently folding those together would hide the malformed id."""
    run_cb("register", "--agent", "planner", "--agent-id", "agent:planner")
    run_cb("register", "--agent", "spectre", "--agent-id", "planner")
    r = run_cb("register", "--agent", "planner", "--agent-id", "agent:planner",
               "--alias", "spectre")
    assert r.returncode != 0
    assert "differs from" in parse_json(r.stderr)["error"]


def test_the_spectre_migration_works_in_two_steps(run_cb, claw_home):
    """Fix the malformed agentId, then absorb — the documented migration path."""
    run_cb("register", "--agent", "planner", "--agent-id", "agent:planner")
    run_cb("register", "--agent", "spectre", "--agent-id", "planner")
    assert run_cb("register", "--agent", "spectre", "--agent-id",
                  "agent:planner").returncode == 0
    assert run_cb("register", "--agent", "planner", "--agent-id", "agent:planner",
                  "--alias", "spectre").returncode == 0
    agents = registry(claw_home)["agents"]
    assert "spectre" not in agents
    assert "spectre" in agents["planner"]["aliases"]
