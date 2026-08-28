"""
T25 — `doctor`: reconcile openclaw.json against the agent registry.

Live evidence this closes. The production ledger (25 bottles, 2026-07-19 → 08-01)
recorded wakes addressed to `SPECTRE` (×5) and `ECHO` (×1) against a registry keyed
on `planner` and `reviewer`, plus `spectre` registered with `agentId: "planner"` —
a logical name in the routing slot. 16% of delegations died silently as a result.
Every one of those is derivable from openclaw.json before a bottle is ever created:
`agents.list[].name` is the persona, `agents.list[].id` is what the registry is keyed
on, and the gap between them is the bug.

The fixture is Albert's real config trimmed to the keys doctor reads.
"""
import json
import shutil

import pytest

from conftest import parse_json

FIXTURE = __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "openclaw.template.json"


@pytest.fixture
def config(tmp_path):
    """A writable copy of the reference config, per test."""
    dst = tmp_path / "openclaw.json"
    shutil.copy(FIXTURE, dst)
    return dst


def patch(cfg_path, mutate):
    d = json.loads(cfg_path.read_text())
    mutate(d)
    cfg_path.write_text(json.dumps(d, indent=2))
    return cfg_path


def with_env(cfg_path):
    """Add the env block a correct install would declare.

    The fixture is Albert's real config, which has no CLAW_CLOSED_TARGET anywhere —
    that absence is a genuine finding and `test_missing_required_env_is_blocking`
    depends on it. Tests that are about *registry* reconciliation patch it in so a
    known-unrelated blocking finding does not mask what they are asserting.
    """
    return patch(cfg_path, lambda d: d["skills"]["entries"].update({
        "interagent-queue": {"env": {"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))


def doctor(run_cb, config, *extra):
    return run_cb("doctor", "--config", str(config), "--json", *extra)


def codes(res):
    return {f["code"] for f in parse_json(res.stdout)["findings"]}


# --------------------------------------------------------------- blocking checks
def test_agent_to_agent_disabled_is_blocking(run_cb, config):
    patch(config, lambda d: d["tools"].__setitem__("agentToAgent", {"enabled": False}))
    res = doctor(run_cb, config, "--all")
    out = parse_json(res.stdout)
    assert res.returncode == 1
    assert out["ok"] is False
    assert "agent-to-agent-disabled" in codes(res)
    # and it must hand back a merge-ready fragment, not just a complaint
    assert out["openclaw_json_fragment"]["tools"]["agentToAgent"] == {"enabled": True}


def test_agent_skills_not_allowed_is_only_a_warning(run_cb, config):
    """We have never verified that `agent-skills` is required — it was observed in one
    working config and nothing more. An unverified claim must not block anyone's setup."""
    patch(config, lambda d: d["plugins"]["allow"].remove("agent-skills"))
    res = doctor(run_cb, config, "--all")
    out = parse_json(res.stdout)
    assert "agent-skills-not-allowed" in codes(res)
    lvl = [f["level"] for f in out["findings"] if f["code"] == "agent-skills-not-allowed"]
    assert lvl == ["warning"], lvl
    # and it must not appear in a fragment telling the user to change their config
    assert "plugins" not in out.get("openclaw_json_fragment", {})


def test_broker_skill_switched_off_is_blocking(run_cb, config):
    patch(config, lambda d: d["skills"]["entries"].__setitem__("miab-broker", {"enabled": False}))
    res = doctor(run_cb, config, "--all")
    assert "skill-disabled" in codes(res)
    assert parse_json(res.stdout)["counts"]["blocking"] >= 1


def test_unreadable_config_fails_closed(run_cb, tmp_path):
    bad = tmp_path / "openclaw.json"
    bad.write_text("{ not json")
    res = run_cb("doctor", "--config", str(bad), "--json")
    assert res.returncode == 1
    assert "config-unreadable" in codes(res)


def test_missing_config_is_reported_not_crashed(run_cb, tmp_path):
    res = run_cb("doctor", "--config", str(tmp_path / "nope.json"), "--json")
    assert res.returncode == 1
    assert parse_json(res.stdout)["ok"] is False


# ------------------------------------------------------------- the SPECTRE bug
def test_persona_not_aliased_is_detected(run_cb, config):
    """reviewer registered under its id only; openclaw.json says it answers to ECHO."""
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer")
    res = doctor(run_cb, config, "--agents", "reviewer")
    assert "persona-not-aliased" in codes(res)
    cmds = parse_json(res.stdout)["commands"]
    assert any("--alias ECHO" in c for c in cmds), cmds


def test_bare_agent_id_is_detected(run_cb, config):
    """`spectre` registered with agentId 'planner' — the real production entry."""
    run_cb("register", "--agent", "planner", "--agent-id", "planner")
    res = doctor(run_cb, config, "--agents", "planner")
    assert "bad-agent-id" in codes(res)
    assert any("--agent-id agent:planner" in c for c in parse_json(res.stdout)["commands"])


def test_ledger_persona_with_no_registry_entry(run_cb, claw_home, config):
    """A wake addressed to SPECTRE, which is nobody's registry key."""
    cb = claw_home / "state" / "callbacks"
    cb.mkdir(parents=True, exist_ok=True)
    (cb / "ledger.jsonl").write_text(
        json.dumps({"at": "2026-08-01T00:00:00Z", "id": "cb-20260801000000-aaaaaa",
                    "event": "return", "by": "SPECTRE", "wake": "main"}) + "\n")
    res = doctor(run_cb, config)
    # SPECTRE folds onto planner: one finding about one agent, not two that disagree
    assert "unregistered" in codes(res)
    assert not any(f.get("agent") == "spectre" for f in parse_json(res.stdout)["findings"])
    cmds = parse_json(res.stdout)["commands"]
    assert any("--agent planner" in c and "--alias SPECTRE" in c for c in cmds), cmds


def test_clean_config_and_registry_exits_zero(run_cb, config):
    with_env(config)
    for agent, persona in [("main", "LYRA"), ("planner", "SPECTRE")]:
        run_cb("register", "--agent", agent, "--agent-id", f"agent:{agent}",
               "--alias", persona, "--display-name", persona)
    res = doctor(run_cb, config, "--agents", "main,planner")
    assert res.returncode == 0, res.stdout
    out = parse_json(res.stdout)
    assert out["ok"] is True
    assert out["commands"] == []


# ------------------------------------------------------- "only as needed" scoping
def test_unused_agents_get_no_proposals(run_cb, config):
    """Albert's constraint: propose only what the broker actually needs."""
    run_cb("register", "--agent", "main", "--agent-id", "agent:main",
           "--alias", "LYRA", "--display-name", "LYRA")
    out = parse_json(doctor(run_cb, config).stdout)
    assert out["commands"] == []
    not_used = {f["agent"] for f in out["findings"] if f["code"] == "not-used"}
    assert {"coder", "debug", "sigma", "local"} <= not_used
    # informational only — never blocking, never a proposed command
    assert all(f["level"] == "info" for f in out["findings"] if f["code"] == "not-used")


def test_all_flag_widens_to_every_declared_agent(run_cb, config):
    out = parse_json(doctor(run_cb, config, "--all").stdout)
    proposed = {f["agent"] for f in out["findings"] if f["code"] == "unregistered"}
    assert len(proposed) == 9


def test_live_bottle_agents_are_always_in_scope(run_cb, config):
    """An in-flight bottle's holder must stay routable even with an empty ledger."""
    run_cb("register", "--agent", "main", "--agent-id", "agent:main", "--alias", "LYRA")
    run_cb("create", "--task", "t", "--from", "main", "--to", "coder", "--summary", "s")
    assert "coder" in {f.get("agent") for f in parse_json(doctor(run_cb, config).stdout)["findings"]}


def test_cold_start_falls_back_to_bindings(run_cb, config):
    out = parse_json(doctor(run_cb, config).stdout)
    assert "cold-start" in {f["code"] for f in out["findings"]}
    # bindings name main/free/utility/sigma/planner — not the whole roster
    proposed = {f["agent"] for f in out["findings"] if f["code"] == "unregistered"}
    assert proposed == {"main", "free", "utility", "sigma", "planner"}


# ----------------------------------------------------------------- side effects
def test_doctor_never_writes_the_config(run_cb, config):
    before = config.read_bytes()
    run_cb("doctor", "--config", str(config), "--all")
    assert config.read_bytes() == before


def test_doctor_never_writes_the_registry(run_cb, claw_home, config):
    reg = claw_home / "state" / "callbacks" / "agent-registry.json"
    run_cb("register", "--agent", "main", "--agent-id", "agent:main")
    before = reg.read_bytes()
    run_cb("doctor", "--config", str(config), "--all")
    assert reg.read_bytes() == before


def test_orphan_registry_entry_is_flagged(run_cb, config):
    run_cb("register", "--agent", "retired-bot", "--agent-id", "agent:retired-bot")
    assert "orphan-registry-entry" in codes(doctor(run_cb, config))


def test_commands_only_emits_runnable_lines(run_cb, config):
    res = run_cb("doctor", "--config", str(config), "--agents", "planner", "--commands-only")
    lines = [l for l in res.stdout.splitlines() if l.strip()]
    assert lines and all(" register --agent " in l for l in lines)


def test_persona_registered_as_its_own_agent_is_folded(run_cb, config):
    """The production shape: a `spectre` entry with agentId 'planner', beside `planner`.

    The repair must be ordered. `register --alias` deliberately refuses to absorb an
    entry whose agentId differs from the target's, so a single fold command would die.
    doctor emits the agentId correction first.
    """
    run_cb("register", "--agent", "spectre", "--agent-id", "planner")
    res = doctor(run_cb, config, "--agents", "planner")
    assert "persona-registered-separately" in codes(res)
    # one agent, one story — no contradictory "planner is unused" alongside it
    assert "not-used" not in {f["code"] for f in parse_json(res.stdout)["findings"]
                              if f.get("agent") == "planner"}
    cmds = parse_json(res.stdout)["commands"]
    assert cmds[0].endswith("register --agent spectre --agent-id agent:planner")
    assert "--agent planner" in cmds[1] and "--alias SPECTRE" in cmds[1]


def test_emitted_repair_commands_actually_run(run_cb, config, claw_home):
    """The proposals are worthless if they fail when pasted. Run them and re-check."""
    with_env(config)
    run_cb("register", "--agent", "spectre", "--agent-id", "planner")
    run_cb("register", "--agent", "reviewer", "--agent-id", "agent:reviewer")
    first = run_cb("doctor", "--config", str(config), "--agents", "planner,reviewer",
                   "--commands-only")
    lines = [l.strip() for l in first.stdout.splitlines() if l.strip()]
    assert lines
    for line in lines:
        argv = line.split()[2:]          # drop "python3 <path>"
        res = run_cb(*argv)
        assert res.returncode == 0, f"proposed command failed: {line}\n{res.stderr}"
    after = doctor(run_cb, config, "--agents", "planner,reviewer")
    assert after.returncode == 0, after.stdout
    assert parse_json(after.stdout)["commands"] == []


# ------------------------------------------- environment, via openclaw.json only
# Retracted the .env approach deliberately: nothing in either skill loads a dotenv
# file, and the gateway launches agents itself, so a shell export is invisible to a
# cron-fired wake -- the path that matters most here. skills.entries[].env is the
# only route that covers every way an agent can be started.

TEMPLATE = __import__("pathlib").Path(__file__).resolve().parents[1] / "miab-broker" / "openclaw.template.json"


def test_missing_required_env_is_blocking(run_cb, config):
    """CLAW_CLOSED_TARGET undeclared -> the queue's notifier fails closed."""
    res = doctor(run_cb, config, "--all")
    out = parse_json(res.stdout)
    assert "env-missing" in codes(res)
    assert out["counts"]["blocking"] >= 1
    frag = out["openclaw_json_fragment"]["skills"]["entries"]["interagent-queue"]["env"]
    assert "CLAW_CLOSED_TARGET" in frag
    # and the suggested value comes from a real binding, not a placeholder
    assert frag["CLAW_CLOSED_TARGET"].startswith("agent:main:discord:channel:")


def test_shell_only_env_is_downgraded_but_still_flagged(run_cb, config):
    """Set in a shell is better than nothing, but will not survive a cron wake."""
    res = run_cb("doctor", "--config", str(config), "--all", "--json",
                 env_overrides={"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"})
    out = parse_json(res.stdout)
    assert "env-shell-only" in {f["code"] for f in out["findings"]}
    assert "env-missing" not in {f["code"] for f in out["findings"]}
    assert out["counts"]["blocking"] == 0


def test_declared_env_satisfies_the_check(run_cb, config):
    patch(config, lambda d: d["skills"]["entries"].update({
        "interagent-queue": {"env": {"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))
    assert "env-missing" not in codes(doctor(run_cb, config, "--all"))


def test_disagreeing_claw_home_is_blocking(run_cb, config):
    """The silent failure: broker writes one ledger, observer reads another."""
    patch(config, lambda d: d["skills"]["entries"].update({
        "miab-broker": {"env": {"CLAW_HOME": "/tmp/root-a"}},
        "interagent-queue": {"env": {"CLAW_HOME": "/tmp/root-b",
                                     "CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))
    res = doctor(run_cb, config, "--all")
    assert "claw-home-disagreement" in codes(res)
    assert parse_json(res.stdout)["counts"]["blocking"] >= 1


def test_matching_claw_home_is_fine(run_cb, config):
    patch(config, lambda d: d["skills"]["entries"].update({
        "miab-broker": {"env": {"CLAW_HOME": "/tmp/same"}},
        "interagent-queue": {"env": {"CLAW_HOME": "/tmp/same",
                                     "CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))
    assert "claw-home-disagreement" not in codes(doctor(run_cb, config, "--all"))


# --------------------------------------------------------- the shipped template
def test_shipped_template_needs_no_config_changes(run_cb):
    """Our own reference config must pass our own config checks.

    Registry findings are expected -- a fresh install has an empty registry. What
    must hold is that the template itself provokes no blocking finding and no
    proposed config fragment, or we are shipping a template doctor rejects.
    """
    res = run_cb("doctor", "--config", str(TEMPLATE), "--all", "--json")
    out = parse_json(res.stdout)
    assert out["counts"]["blocking"] == 0, [f for f in out["findings"] if f["level"] == "blocking"]
    assert "openclaw_json_fragment" not in out, out.get("openclaw_json_fragment")


def test_shipped_template_is_valid_json_and_self_documenting(run_cb):
    d = json.loads(TEMPLATE.read_text())
    assert "DELETE_THIS_KEY_BEFORE_USE" in d["_miab_broker_template"]
    assert d["tools"]["agentToAgent"]["enabled"] is True
    # every agent carries both the routing id and the persona the registry needs aliased
    assert all("id" in a and "name" in a for a in d["agents"]["list"])
