# miab-suite — ROADMAP

> Last updated **2026-08-29**. Owns forward planning; supersedes `miab-broker-execution-backlog.md`, `miab-broker-feature-roadmap.md`, and `miab-broker-M3-scope.md` (originals deleted 2026-08-31). T/Q numbering is preserved from the retired backlog. Current state lives in `STATUS.md`; shipped history in `HISTORY.md`.

Ordering principle, unchanged: *exploitable now → silently losing data → producing wrong results → missing guarantees → ergonomics*.

## Shipped (context)

| release | theme | date |
|---|---|---|
| broker 1.2.0 / 1.2.1 | M1 exploit closed (T1–T7 + punchlist) | 2026-08 |
| broker 1.3.0 | M2 docs/permissions/SECURITY.md + T22 sessionKey routing | 2026-08-08 |
| interagent-queue 1.3.0 | cursor fail-closed, honest declarations, deprecation → miab-observer | 2026-08-28 |
| broker 2.0.0 + observer 2.0.0 | M3 trustworthy routing (T14/T15/T12/Q9) + T23 + rename | 2026-08-29 |

---

## R1 — broker 2.1.0: `doctor` + `hops` — **next up, in progress** (target: ~Sep 6)

Branch `t25-doctor` (`4673bcd`) already carries the feature complete with 141 passing tests.

1. **Rebase `t25-doctor` onto `main`** — it branched pre-rename; observer paths in tests/fixtures must move to `miab-observer/`.
2. **T25 `doctor`** (done on branch): reconciles `openclaw.json` + `agent-registry.json` + the ledger; graded findings (blocking/routing/warning/info); emits a merge-ready config fragment, never writes; `openclaw.template.json` ships beside SKILL.md. Remaining polish: run `doctor --json` against the live `~/.openclaw` (fixtures reproduce known bugs; the live registry may hold others); settle the `agent-skills` warning (see STATUS punchlist); optionally add a test reading the shipped template as the authoritative key list.
3. **T24 `hops` fix** (~1 h) — fold into this release. Three contradictory definitions exist (`len(env["results"])` in the CLI, `len(bottle_records)` in the retired notifier path, nothing in the envelope). It is LATE against its own constraint: it must land **before** R2's reader rewrite canonicalises a wrong definition, and `stats` (T20) is wrong until it lands. The observer does not read `hops`, so the coupling rule does not bind — fix in place.
4. Blocked on Albert: `CLAW_CLOSED_TARGET` choice (doctor reports its absence as blocking against the live config — correctly).

Release: broker **2.1.0** (additive; VERSION already stamped on the branch). Publish from the post-rebase merge commit.

## R2 — observer 2.1.0: the Phase 2 reader rewrite (target: ~Sep 20)

ADR-001 Phase 2, the half not yet done. Merge `notify_closed_bottles.py` into `miab_observer.py`: **one cursor, one dedup model, one registry-sourced identity map**, pluggable sinks (`log`, `message`) — the structural fix for the two-cursor double-post class of bug. Fold the security catch-up in while the program is open rather than as a separate pass:

- **Q1** path containment — `.resolve()` + confinement on all nine env-derived paths (`CLAW_QUEUE_LOG` is an arbitrary-append primitive today).
- **Q3** file modes — `umask 0o077` + 0700/0600 (broker has this + tests; observer still writes state/log at ambient umask holding task/result text; shipped that way in 1.3.0).
- **Q4/Q8** — specific exception handling on state load (no silent cursor reset) and unique tmp names in `save_state`.
- **Q6** — observer `SECURITY.md` + `README.md`; declare network honestly for the message sink.
- **Q7** — broker version floor as a runtime gate, not prose.
- Retire `notify_closed_dryrun.py` into a `--dry-run` flag (ADR item 10).

Constraint: **T24 must already be merged** (R1) before this rewrite.

## R3 — broker 2.2.0: M4 "no silent data loss" (target: ~mid-Oct)

- **T11** envelope durability — `flock` per envelope, pid-tagged tmp names, quarantine on parse failure. The xfail repro (20 parallel forwards → corrupt zombie bottle) has been waiting since M1; flip its marker to `strict` when it lands. Unblocks T13, T19.
- **T13** lifecycle consistency — archive-on-fail as well as cancel, `sweep --prune-archive 30d` (glob `cb-*.json` only — `archive/` holds foreign session transcripts), byte-based ledger rotation, document-or-remove `state/callbacks/trash/`.
- Risk note: T11's failure mode is still theoretical on live traffic (all forwards serial to date), but any move toward parallel fan-out makes it urgent overnight.

## R4 — broker 2.3.0 + observer 2.2.0: M5 at-least-once delivery (target: ~Nov, includes a 1-week reaper soak)

- **T16** per-bottle TTL (`create --ttl`, `deadlineAt`, default raised to 24 h from observed p90, `DUE` on `list`) — the gate on ever enabling the reaper.
- **T17** delivery guarantees — `delivery: {attempts, lastWakeAt, maxAttempts}`; sweep becomes re-wake → dead-letter → notify root; `nack`.
- **Q10** observer renderers for every new event type (`redeliver`, `nack`, dead-letter) — the coupling rule; ships as the observer minor bump.
- **T18** enable the reaper (ops): cron `--dry-run` one week → review → `--fail`; fix `parse_age_minutes`; gate the blind tmp cleanup on mtime.

## R5 — broker 2.4.0: M6 tamper evidence (target: ~Dec, demand-driven)

- **T19** per-envelope HMAC keyed by a 0600 file, verified on load, mismatches quarantined to `archive/tampered/`; monotonic `seq`; terminal states non-reopenable. Depends on T11. Closes the audit's remaining `persistence_privilege` thesis and the "`--force` is unauthenticated" caveat from M3.

## R6 — M7 ergonomics (unscheduled; pick up opportunistically)

- **T20** `stats` / `history` — correct only after T24; `doctor` (the third leg) ships in R1.
- **T21** `dispatch` fuse create+wake (88% of chains are single-hop and pay two round trips) + `--compact` output.
- Q11 is already decided by ADR-001: analytics in the writer, presentation in the reader.

---

## Not scheduled / standing decisions

- `doctor --fix` — **rejected**; don't add without re-arguing (a wrong automated config write costs more than the manual paste saves).
- A third delivery sink for the observer — revisit rather than generalise; two sinks, no registry.
- Layout changes (`skills/<name>/`) — closed by ADR-001 amendment.
- Never schedule the reaper before T16 lands (26% of real returns exceed the old 120 m default).
