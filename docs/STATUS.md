# miab-suite — STATUS

> Sanitized 2026-08-31 for the public repo: live channel ids and personal identifiers are redacted; live values are in local config and project memory. Excluded from ClawHub packages (publish archives the skill dir only).
> Last full update: **2026-09-01** (R1 code-complete; git state refreshed the same day). Partial update **2026-10-02**: the OpenClaw 2026.9.3 `agents.entries` migration (section below, git state, punchlist). Replaces `MIGRATION_PROMPT.md`, `T25-doctor-handoff.md`, `T25-doctor-pickup.md`, `miab-monorepo-kickoff-prompt.md`, `miab-broker-m3-kickoff.md` (originals deleted 2026-08-31).

## What this is

A monorepo of two OpenClaw skills for token-conserving multi-agent delegation:

- **miab-broker** — the writer. `claw-callback.py`, a stdlib-only Python 3 CLI implementing the message-in-a-bottle LIFO callback stack (`register → create → wake → forward → return → resolve`, plus `cancel/show/list/sweep/doctor`) over `$CLAW_HOME/state/callbacks/` with an append-only `ledger.jsonl` audit spine.
- **miab-observer** — the reader (formerly `interagent-queue`). `miab_observer.py` renders ledger events to a log; `notify_closed_bottles.py` (moved here by T23) posts closed-bottle summaries to chat.

Repo: `~/.openclaw/skills/miab-suite` (working tree on the Mac; dir renamed from `miab-broker+interagent-queue`). Remote: `git@github.com:albzhu/miab-broker.git` as `upstream`. Layout: `miab-broker/`, `miab-observer/`, `tests/` (repo root), `artifacts/`, `_to_delete/`. Governing decision record: `ADR-001-skill-and-repo-boundaries.md`.

## Released (ClawHub) — as of 2026-08-29

| skill | live version | published | from commit |
|---|---|---|---|
| miab-broker | **2.0.0** (M3 trustworthy routing; breaking) | 2026-08-29 | `d31f969` |
| miab-observer | **2.0.0** (first publish under new name) | 2026-08-29 | `d31f969` |
| interagent-queue | **1.3.0** — deprecation release pointing users at miab-observer; also remediated the host-username leak public since 1.2.0 (2026-07-22) | 2026-08-28 | `913f8b2` |

## OpenClaw 2026.9.3 roster migration — 2026-10-02

OpenClaw 2026.9.3 (reference deployment upgraded 2026-09-24) moved the agent roster in `openclaw.json` from `agents.list` — an array of `{id, name, …}` — to `agents.entries`, a dict keyed on the agent id whose values carry `name` and no `id`. Shape confirmed by reading the live config on 2026-10-02 (nine entries, none with an `id` field).

- **Impact.** `doctor` was the only code that parsed the roster. On a migrated config it found nobody: a false blocking `no-agents`, exit 1, and every registry entry reported as an orphan. `register` / `wake` / `forward` / `return` / `resolve` never read `openclaw.json` and were unaffected; `agent-registry.json` semantics are unchanged.
- **Fix (`ca59fd3` on `t25-doctor`, rides in 2.1.0).** `doctor` reads `agents.entries` and treats the entry **key** as the functional id; persona folding and the emitted `register` commands are unchanged — a test asserts both shapes emit byte-identical commands. A stray `id` inside a keyed entry is ignored.
- **Legacy shape kept (decided 2026-10-02).** `agents.list` is still read when `agents.entries` is absent or empty, so installs on OpenClaw < 2026.9.3 keep working. That path raises a new advisory `legacy-agents-list` warning, which never affects the exit code and names its own uncertainty: doctor cannot see the gateway version. When both shapes are present, `agents.entries` wins.
- **Also updated.** `miab-broker/openclaw.template.json` and `tests/fixtures/openclaw.template.json` ship the keyed shape; `SKILL.md`, the CHANGELOG 2.1.0 entry and the observer's `MODEL_MAP` comment use the new name. The observer parses no config — its agent and model maps are hardcoded — so nothing there changed behaviour.
- **Verified 2026-10-02, off-Mac (device bridge).** Suite **158 passed / 1 xfailed** (six roster-shape tests, three for `--ignore` / internal actors). `doctor --json` against the live config: **0 blocking, 0 routing, exit 0**; the pre-fix code on the same config exits 1 with `no-agents`.

## Git state

- `main` = `2bfb595` (the sanitized-docs commit, on top of `d31f969`). **Ahead 9 of `upstream/main` — push pending.**
- `t25-doctor` = `ca59fd3` (as of 2026-10-02), **rebased onto `main`** and **code-complete for R1**. Five commits atop `main`: the `doctor` subcommand, rename alignment + test-fixture scrub, the T24 `hops` fix, and the fragment-fill correction that came out of the first `doctor --json` run against a live install. and the `agents.entries` migration above. Suite on the branch: **158 passed / 1 xfailed**. The rebase went through a bundle round trip, not a checkout — the device bridge cannot perform a checkout that deletes files.
- The pre-rebase branch head, which predates the fixture scrub, carries real identifiers in `tests/fixtures/openclaw.template.json` and **must never be pushed**. The rebased branch replaced them with synthetic ids.
- Merged, deletable after push: `release-iq-1.3.0`, `rename-miab-observer`, `m3-trustworthy-routing`. A stray loose ref `refs/bundles/t25` is left over from the round trip — harmless, delete Mac-side.
- Tags `v1.3.0`, `v2.0.0` — tag *dates* are unreliable (history reconstructed ~08-19); trust the ClawHub listing for publish dates.

## Standing constraints (full rationale in ADR-001 + HISTORY.md)

1. **Never add a root `SKILL.md`** — the loader would treat the repo root as the only skill; both skills vanish silently (verified on openclaw npm 2026.7.1-2).
2. **Never rename the state files** `queue_state.json`, `closed_bottle_state.json`, `$CLAW_HOME/logs/interagent-queue.log` — they key on `CLAW_HOME`, not skill name. Renaming the cursor file replays the entire ledger (the bug 1.3.0 fixed). The log still saying `interagent-queue` is correct.
3. **No `.env`, ever** (retracted 2026-08-27). Env goes in `openclaw.json` `skills.entries.<skill>.env` — the only route a cron-fired wake sees.
4. **Permissions declarations stay honest** — this repo shipped falsified declarations twice. Broker 2.0.0: `env: [CLAW_HOME, CALLBACK_TTL_MIN]`, zero egress. Observer: nine env vars read, nine declared. doctor adds `file_read: $CLAW_HOME/openclaw.json` + env `OPENCLAW_CONFIG`, `OPENCLAW_WORKSPACE_ROOT`, `CLAW_CLOSED_TARGET`.
5. **No `version` in SKILL.md frontmatter** — ClawHub owns the version.
6. **Layout is `<name>/` at repo root** — decided; don't re-propose `skills/<name>/`.
7. **No push, tag, or publish without Albert's review.** Public repo: no host paths, secrets, or channel ids in committed text.
8. **The coupling rule**: every new ledger event type needs a matching observer renderer + test, or it renders as nothing, silently (`corrupt` in 1.2.0; nearly `authority-override` in 2.0.0).
9. The ledger record schema is a compatibility contract: new optional keys fine; renaming/removing existing ones is not. Every mutating subcommand prints a `next_step`; failures fail closed (`{"ok": false, …}`, non-zero exit). Tests only ever run against `CLAW_HOME=$(mktemp -d)`.
10. Evidence rule: never promote a single observation into a blocking assertion — thin evidence becomes a warning that names its own uncertainty and the command that settles it.

## Ops punchlist (needs a human / Mac shell)

Ordered; the first four gate the 2.1.0 publish.

- [x] ~~**Commit the `agents.entries` migration** on `t25-doctor`.~~ Done 2026-10-02 as `ca59fd3` (seven files; `docs/` left unstaged for the merge commit).
- [ ] **Run the suite once on the Mac** from a `t25-doctor` checkout: `python3 -m pytest --ignore=_to_delete`. The 158/1 figure (2026-10-02) has been verified off-Mac only.
- [ ] **Re-run `doctor --json` from a Mac shell** after the migration. The 2026-10-02 bridge run was clean on blocking/routing but also reported `skill-dir-not-scanned` and `env-shell-only`, which are probably artifacts of the bridge's mount path — a native run settles it. The two `unknown-agent` warnings it showed are handled (2026-10-02): `sweep` is the broker's own reaper and is no longer reported (nor is `system`); `self-maintenance` is a single old `--to` in the ledger — pass `--ignore self-maintenance`.
- [x] ~~**Run `doctor --json` against the live config.**~~ Done 2026-09-01. Transport and `CLAW_HOME` are clean; the `persona-registered-separately` finding is the known shape with a safe ordered repair. It also surfaced that the fragment auto-filled `CLAW_CLOSED_TARGET` from an arbitrary one of several `main` bindings — fixed, with tests, because the fixture's single binding could not express the ambiguity. Two checks that fired live (`unknown-agent`, `session-key-unverified`) had no coverage and now do.
- [ ] **Resolve the `session-key-unverified` finding on `main`** — its registered sessionKey matches no `bindings[]` entry, so if that session is gone every wake for `main` lands nowhere. Graded `warning` correctly (doctor cannot verify a session exists), but confirm out-of-band; the ledger would show wakes with no follow-on activity. (It did not fire in the 2026-10-02 bridge run; not yet confirmed from the Mac.)
- [x] ~~**Pick the real `CLAW_CLOSED_TARGET`.**~~ Chosen and declared in `skills.entries["miab-observer"].env` 2026-09-01. doctor now returns **0 blocking, 0 routing** against the live config; the emitted `register` command for the `persona-registered-separately` finding was run and cleared it — the first time the repair-command path has been exercised outside the test suite.
- [x] ~~**Settle doctor's `agent-skills` warning.**~~ Resolved 2026-09-01: dropped. The plugin is unrelated to this skill — it is allowed in the reference deployment for a planner's spec-driven development. The warning was a correlation in a single config; the check, its test, the SKILL.md caveat and the template's `plugins` block are all gone.
- [ ] **Merge `t25-doctor` → `main`** (`--no-ff`), fold this docs refresh into the merge, `git push -u upstream main` + tags, then publish broker **2.1.0** from the merge commit.
- [ ] `rm -rf _to_delete/ .git/_to_delete/` (~85 parked lock files; the device bridge cannot unlink), delete the three merged branches, delete `refs/bundles/t25`.

Standing, not gating 2.1.0:

- [ ] **Fix the cron `--command` path** for the closed-bottle notifier — it still points at the pre-T23 location, broken by both the script move and the directory rename. It fails silently.
- [ ] Verify `openclaw.json` `skills.entries` paths post-rename with `openclaw skills list --verbose` — the loader keys on frontmatter `name`, not path, so shadowing is silent.
- [ ] Verify the observer's non-empty `network:` value against ClawHub's schema (currently a descriptive string, still a guess).
- [ ] Check the chat channel for closed-bottle summaries from other people's unconfigured 1.3.0 installs.

## Environment quirks (Cowork device bridge → Mac)

`device_bash` cannot unlink: park git `*.lock` files into `.git/_to_delete/` via `mv`; unwanted files go to `_to_delete/`. No git identity in the VM — pass `-c user.name=… -c user.email=…` per command (values in project memory). Never touch the network from the bridge (no SSH known_hosts) — push/pull/publish from a Mac shell. `python3 -m pip install --user pytest` first; run `python3 -m pytest --ignore=_to_delete`. Checkouts that must delete files fail midway; recover with parked locks + `git read-tree HEAD`, restore via `git show HEAD:path > path`, commit via temp index + `git commit-tree` + `update-ref`.
