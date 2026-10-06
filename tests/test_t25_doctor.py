"""
T25 — `doctor`: reconcile openclaw.json against the agent registry.

Live evidence this closes. The production ledger (25 bottles, 2026-07-19 → 08-01)
recorded wakes addressed to `SPECTRE` (×5) and `ECHO` (×1) against a registry keyed
on `planner` and `reviewer`, plus `spectre` registered with `agentId: "planner"` —
a logical name in the routing slot. 16% of delegations died silently as a result.
Every one of those is derivable from openclaw.json before a bottle is ever created:
`agents.entries[<id>].name` is the persona, the `agents.entries` key is what the registry
is keyed on, and the gap between them is the bug.

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
        "miab-observer": {"env": {"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))


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
    frag = out["openclaw_json_fragment"]["skills"]["entries"]["miab-observer"]["env"]
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
        "miab-observer": {"env": {"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))
    assert "env-missing" not in codes(doctor(run_cb, config, "--all"))


def test_disagreeing_claw_home_is_blocking(run_cb, config):
    """The silent failure: broker writes one ledger, observer reads another."""
    patch(config, lambda d: d["skills"]["entries"].update({
        "miab-broker": {"env": {"CLAW_HOME": "/tmp/root-a"}},
        "miab-observer": {"env": {"CLAW_HOME": "/tmp/root-b",
                                     "CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}}))
    res = doctor(run_cb, config, "--all")
    assert "claw-home-disagreement" in codes(res)
    assert parse_json(res.stdout)["counts"]["blocking"] >= 1


def test_matching_claw_home_is_fine(run_cb, config):
    patch(config, lambda d: d["skills"]["entries"].update({
        "miab-broker": {"env": {"CLAW_HOME": "/tmp/same"}},
        "miab-observer": {"env": {"CLAW_HOME": "/tmp/same",
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
    # keyed roster (OpenClaw >= 2026.9.3): the key is the routing id, `name` the persona
    assert "list" not in d["agents"]
    assert d["agents"]["entries"] and all("name" in a and "id" not in a
                                          for a in d["agents"]["entries"].values())


# ------------------------------------------------------- legacy entry key (2.0.0 rename)
def test_legacy_observer_entry_is_warned_but_honoured(run_cb, config):
    """Pre-rename configs key the reader's entry by 'interagent-queue'. The env it
    declares is what the install actually runs with, so it must satisfy the checks;
    the stale key itself is a warning that names the rename and the settling command."""
    def mut(d):
        e = d["skills"]["entries"]
        e.pop("miab-observer", None)
        e["interagent-queue"] = {"env": {"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}}
    patch(config, mut)
    cs = codes(doctor(run_cb, config, "--all"))
    assert "legacy-observer-entry" in cs
    assert "env-missing" not in cs           # the legacy env block is honoured
    assert "duplicate-observer-entry" not in cs


def test_duplicate_observer_entries_prefer_the_new_name(run_cb, config):
    """Both keys present: 'miab-observer' wins, and the duplication is its own finding."""
    patch(config, lambda d: d["skills"]["entries"].update({
        "miab-observer": {"env": {"CLAW_CLOSED_TARGET": "agent:main:discord:channel:123"}},
        "interagent-queue": {"env": {}}}))
    cs = codes(doctor(run_cb, config, "--all"))
    assert "duplicate-observer-entry" in cs
    assert "legacy-observer-entry" not in cs
    assert "env-missing" not in cs           # satisfied via the preferred entry


# ------------------------------------------- the fragment must not choose for you
# Added 2026-09-01 after the first `doctor --json` run against the live config. The
# fixture carries ONE binding for `main`; the live config carries eight. That gap is
# why the auto-fill below shipped untested: with a single candidate the old
# `sess_cands["main"][0]` was always right, and with several it silently picked the
# first in bindings[] order. Two runs a day apart suggested two different channels.

def test_closed_target_is_filled_when_there_is_exactly_one_candidate(run_cb, config):
    """One binding is unambiguous, so filling it in is a real convenience — keep it."""
    mains = [b for b in json.loads(config.read_text())["bindings"]
             if b.get("agentId") == "main"]
    assert len(mains) == 1, "this test is about the single-candidate case"
    peer = mains[0]["match"]["peer"]["id"]
    out = parse_json(doctor(run_cb, config, "--all").stdout)
    frag = out["openclaw_json_fragment"]["skills"]["entries"]["miab-observer"]["env"]
    assert frag["CLAW_CLOSED_TARGET"] == f"agent:main:discord:channel:{peer}"
    msg = [f["message"] for f in out["findings"] if f["code"] == "env-missing"][0]
    assert "The only binding" in msg


def test_closed_target_is_not_auto_filled_when_ambiguous(run_cb, config):
    """Several `main` bindings -> the fragment says REPLACE_ME and names them all.

    The hazard 2.0.0 closed was misdirected delivery to a chat channel, remediated by
    making CLAW_CLOSED_TARGET required and failing closed. A fragment that pre-fills an
    arbitrary one of several channels while calling itself merge-ready re-creates that
    hazard for whoever pastes it. One candidate is a suggestion; several is a choice
    only the operator can make.
    """
    def add_two_more_main_bindings(d):
        proto = next(b for b in d["bindings"] if b.get("agentId") == "main")
        for peer in ("100000000000000009", "100000000000000010"):
            clone = json.loads(json.dumps(proto))
            clone["match"]["peer"]["id"] = peer
            d["bindings"].append(clone)
    patch(config, add_two_more_main_bindings)

    out = parse_json(doctor(run_cb, config, "--all").stdout)
    frag = out["openclaw_json_fragment"]["skills"]["entries"]["miab-observer"]["env"]
    assert frag["CLAW_CLOSED_TARGET"] == "REPLACE_ME", frag
    msg = [f["message"] for f in out["findings"] if f["code"] == "env-missing"][0]
    assert "3 bindings exist for 'main'" in msg, msg
    # naming every candidate is the point: the operator cannot choose from a count
    for peer in ("100000000000000009", "100000000000000010"):
        assert peer in msg, msg


# ------------------------------- checks that fired on the live config untested (R1)
def test_unknown_agent_in_broker_state_is_a_warning(run_cb, config):
    """A `--to` that is neither an agents.entries id nor any persona name.

    Live shape: a `self-maintenance` caller in the ledger with no matching agent.
    Warning, not routing: doctor cannot tell a retired agent from a typo, and the
    evidence rule says an unverifiable claim does not get to fail anyone's build.
    """
    with_env(config)
    res = run_cb("create", "--task", "housekeeping", "--from", "main",
                 "--to", "self-maintenance", "--summary", "s")
    assert res.returncode == 0, res.stderr

    out = parse_json(doctor(run_cb, config).stdout)
    codes_seen = {f["code"] for f in out["findings"]}
    assert "unknown-agent" in codes_seen
    f = next(x for x in out["findings"] if x["code"] == "unknown-agent")
    assert f["level"] == "warning", f
    assert f["agent"] == "self-maintenance"
    # distinct from the orphan case: nothing was ever registered under that name
    assert "orphan-registry-entry" not in codes_seen


def test_session_key_matching_no_binding_is_flagged(run_cb, config):
    """A registered sessionKey the config does not imply -> wakes may reach nobody.

    Warning, not blocking, deliberately: doctor can see that a key matches no
    bindings[] entry, but not whether the session behind it still exists. Same
    consequence as `agent-to-agent-disabled`, weaker evidence, lower grade.
    """
    with_env(config)
    run_cb("register", "--agent", "main", "--agent-id", "agent:main",
           "--session-key", "agent:main:discord:channel:999999999999999999")

    out = parse_json(doctor(run_cb, config, "--agents", "main").stdout)
    f = next(x for x in out["findings"] if x["code"] == "session-key-unverified")
    assert f["level"] == "warning", f
    assert f["agent"] == "main"
    # the fix has to name the sessions the config actually implies, not just complain
    assert "agent:main:discord:channel:100000000000000001" in f["fix"], f["fix"]


# ------------------------------------------- roster shape (OpenClaw 2026.9.3 migration)
# 2026.9.3 moved the roster from agents.list (array of {id, name}) to agents.entries
# (dict keyed on id; values carry `name` and no `id`). The fixture is the keyed shape.
def _to_legacy_list(d):
    entries = d["agents"].pop("entries")
    d["agents"]["list"] = [{"id": k, **v} for k, v in entries.items()]


def test_keyed_roster_is_not_reported_empty(run_cb, config):
    """The regression itself: reading agents.list on a 9.3 config found nobody."""
    d = json.loads(config.read_text())
    assert "entries" in d["agents"] and "list" not in d["agents"]
    res = doctor(run_cb, with_env(config), "--all")
    assert "no-agents" not in codes(res)
    assert "legacy-agents-list" not in codes(res)
    # the key is the functional id, and the persona folds onto it as an alias
    cmds = parse_json(res.stdout)["commands"]
    assert any("register --agent planner " in c and "agent:planner" in c and "SPECTRE" in c
               for c in cmds), cmds


def test_keyed_roster_ignores_a_stray_id_field(run_cb, config):
    """The entry KEY is the id; a leftover `id` inside the value must not re-key it."""
    patch(config, lambda d: d["agents"]["entries"]["planner"].__setitem__("id", "somebody-else"))
    res = run_cb("doctor", "--config", str(with_env(config)), "--agents", "planner",
                 "--commands-only")
    assert "register --agent planner " in res.stdout and "agent:planner" in res.stdout
    assert "somebody-else" not in res.stdout


def test_legacy_list_roster_still_reconciles_and_warns(run_cb, config):
    patch(with_env(config), _to_legacy_list)
    keyed = run_cb("doctor", "--config", str(config), "--all", "--commands-only")
    out = parse_json(doctor(run_cb, config, "--all").stdout)
    found = {f["code"]: f for f in out["findings"]}
    assert "no-agents" not in found
    assert found["legacy-agents-list"]["level"] == "warning"   # advisory: never fails the run
    assert "register --agent planner " in keyed.stdout


def test_both_shapes_emit_identical_register_commands(run_cb, config, tmp_path):
    with_env(config)
    legacy = tmp_path / "legacy.json"
    shutil.copy(config, legacy)
    patch(legacy, _to_legacy_list)
    a = run_cb("doctor", "--config", str(config), "--all", "--commands-only").stdout
    b = run_cb("doctor", "--config", str(legacy), "--all", "--commands-only").stdout
    assert a.strip() and a == b


def test_entries_wins_when_both_shapes_are_present(run_cb, config):
    patch(with_env(config), lambda d: d["agents"].__setitem__(
        "list", [{"id": "ghost", "name": "GHOST"}]))
    res = doctor(run_cb, config, "--all")
    assert "legacy-agents-list" not in codes(res)
    assert not any("ghost" in c for c in parse_json(res.stdout)["commands"])


def test_empty_roster_is_blocking_in_either_shape(run_cb, config):
    for mutate in (lambda d: d["agents"].__setitem__("entries", {}),
                   lambda d: d.__setitem__("agents", {"list": []}),
                   lambda d: d.pop("agents")):
        patch(config, mutate)
        res = doctor(run_cb, config)
        assert "no-agents" in codes(res)
        assert res.returncode == 1


# ------------------------------------------------- unknown-agent: actors and --ignore
def _ledger_with(claw_home, *records):
    cb = claw_home / "state" / "callbacks"
    cb.mkdir(parents=True, exist_ok=True)
    (cb / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def _unknown(res):
    return {f["agent"] for f in parse_json(res.stdout)["findings"] if f["code"] == "unknown-agent"}


def test_broker_internal_actors_are_not_unknown_agents(run_cb, claw_home, config):
    """Live shape: `by: sweep` on a reaped bottle was reported as an unknown agent."""
    _ledger_with(claw_home,
                 {"id": "cb-1", "event": "fail", "by": "sweep"},
                 {"id": "cb-2", "event": "corrupt", "by": "system"},
                 {"id": "cb-3", "event": "create", "by": "main", "to": "nobody-at-all"})
    assert _unknown(doctor(run_cb, with_env(config))) == {"nobody-at-all"}


def test_ignore_drops_named_unknown_agents_only(run_cb, claw_home, config):
    _ledger_with(claw_home,
                 {"id": "cb-1", "event": "create", "by": "main", "to": "self-maintenance"},
                 {"id": "cb-2", "event": "create", "by": "main", "to": "typo-agent"})
    with_env(config)
    assert _unknown(doctor(run_cb, config)) == {"self-maintenance", "typo-agent"}
    assert _unknown(doctor(run_cb, config, "--ignore", "Self-Maintenance")) == {"typo-agent"}


def test_ignore_never_hides_a_registered_name(run_cb, claw_home, config):
    """Something registered can be woken, so an orphan stays visible whatever is ignored."""
    with_env(config)
    r = run_cb("register", "--agent", "sweep", "--agent-id", "agent:sweep")
    assert r.returncode == 0, r.stderr
    res = doctor(run_cb, config, "--ignore", "sweep")
    orphans = {f["agent"] for f in parse_json(res.stdout)["findings"]
               if f["code"] == "orphan-registry-entry"}
    assert "sweep" in orphans

