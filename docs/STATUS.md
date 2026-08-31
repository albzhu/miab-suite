# miab-suite — STATUS

> Sanitized 2026-08-31 for the public repo: live channel ids and personal identifiers are redacted; live values are in local config and project memory. Excluded from ClawHub packages (publish archives the skill dir only).
> Last full update: **2026-08-29** (git state refreshed 2026-08-31). Replaces `MIGRATION_PROMPT.md`, `T25-doctor-handoff.md`, `T25-doctor-pickup.md`, `miab-monorepo-kickoff-prompt.md`, `miab-broker-m3-kickoff.md` (originals deleted 2026-08-31).

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

## Git state

- `main` = `d31f969` + the 2026-08-31 sanitized-docs commit (linear history through the 1.3.0 deprecation, the miab-observer rename `67dc035`, and the provenance fix). **Ahead 9 of `upstream/main` — push pending.**
- `t25-doctor` = `4673bcd`, branched off `857c538` (pre-rename). Carries the `doctor` subcommand (broker VERSION 2.1.0), suite 141 passed / 1 xfailed. **Needs a rebase onto `main`** before PR — it predates the rename, so observer paths there still say `interagent-queue`.
- Merged, deletable after push: `release-iq-1.3.0`, `rename-miab-observer`, `m3-trustworthy-routing`.
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

- [ ] `git push -u upstream main` (also fixes the missing tracking branch) + push tags.
- [ ] `rm -rf _to_delete/ .git/_to_delete/` in the repo (~90 parked lock files; device bridge cannot unlink). The old docs folder's `_to_delete/` was removed 2026-08-31.
- [ ] Delete merged branches.
- [ ] **Fix the cron `--command` path** for the closed-bottle notifier — it still points at `miab-broker/scripts/notify_closed_bottles.py`, broken by T23's move *and* the directory rename; it fails silently.
- [ ] Verify `openclaw.json` `skills.entries` paths post-rename and run `openclaw skills list --verbose` — loader keys on frontmatter `name`, not path, so shadowing/breakage is silent.
- [ ] **Pick the real `CLAW_CLOSED_TARGET`.** doctor suggests a specific `agent:main:discord:channel:<id>` (derived from session-pin-clear, not confirmed; candidate id redacted here — see doctor's own output or project memory). Until set, the notifier fails closed — currently by configuration, deliberately.
- [ ] Settle doctor's `agent-skills` warning: scratch config without it in `plugins.allow`, `openclaw skills list --verbose`; promote to blocking or drop.
- [ ] Verify the observer's non-empty `network:` value against ClawHub's schema (currently a descriptive string, still a guess).
- [ ] Check the Discord channel for closed-bottle summaries from other people's unconfigured 1.3.0 installs.

## Environment quirks (Cowork device bridge → Mac)

`device_bash` cannot unlink: park git `*.lock` files into `.git/_to_delete/` via `mv`; unwanted files go to `_to_delete/`. No git identity in the VM — pass `-c user.name=… -c user.email=…` per command (values in project memory). Never touch the network from the bridge (no SSH known_hosts) — push/pull/publish from a Mac shell. `python3 -m pip install --user pytest` first; run `python3 -m pytest --ignore=_to_delete`. Checkouts that must delete files fail midway; recover with parked locks + `git read-tree HEAD`, restore via `git show HEAD:path > path`, commit via temp index + `git commit-tree` + `update-ref`.
