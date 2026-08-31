# miab-suite — HISTORY

> Condensed archive, written 2026-08-29. Coalesces `miab-broker-review.md`, `miab-broker-security-remediation.md`, `M1-agent-prompt.md`, `M1-completion.md`, `M1-punchlist-completion.md`, `M3-completion.md`, and `miab-messaging-dedup-and-cron-sequencing.md` (originals deleted 2026-08-31; this condensed archive is the sole surviving record). Sanitized 2026-08-31 for the public repo — live channel ids and personal identifiers are redacted; live values are in local config and project memory.

## Origin: review + audit of 1.1.1 (2026-08)

ClawHub's scanners rated 1.1.1 `suspicious` (no malware; thesis: "stores and mutates inter-agent callback state on disk without access-control or integrity safeguards" — correct). An internal review found worse than the audit did:

- **S0 (not in the audit)**: unvalidated `--id` was an arbitrary-file read/write/**delete** primitive — `show --id "../../victim"` read any `.json`, `resolve` unlinked it; reachable via prompt injection through `callback://<id>` text. On this host that reach included `auth.json` holding an API key.
- Fixed tmp path made concurrent writes corrupt envelopes into "immortal zombies" invisible to `list`/`sweep` (20 parallel forwards → 15 of 20 ledger events lost).
- Every documented invocation path was wrong (four variants, none resolved).
- No authority checks: any agent could pop another's frame or resolve/destroy any bottle (observed live). No redelivery: 16% of delegations silently died; the reaper had never run — the only reason nothing was lost (26% of real returns exceeded its 120 m default).
- Identity broken in practice: personas (`SPECTRE`, `ECHO`) vs functional registry keys (`planner`, `reviewer`); `spectre` registered with malformed `agentId: "planner"`.

**2026-08-07 docs deletion**: an agent task "clean up unused copies of the miab-broker skill" swept the docs directory; six planning docs were lost, none committed, all reconstructed 2026-08-08. Lesson institutionalised: commit the docs directory.

## M1 "exploit closed" — broker 1.2.0 / 1.2.1 (T1–T7)

Id validation + path containment (S0), self-referential command paths, pytest harness, `CLAW_HOME` ownership/mode validation, `umask 0o077` + 0700/0600 modes, fail-closed everywhere (incl. quarantine of corrupt envelopes + `corrupt` ledger event), resume-input confinement/schema. Punchlist 1.2.1: the T4 mode check was numeric (`> 0o700`) not a bitmask — `0o550/0o540/0o505` wrongly accepted (tests had been written to the implementation); the `corrupt` event was invisible to the observer (first firing of the coupling rule); SKILL.md path form; repo hygiene. Post-review audit found 11 deployed copies of the CLI, 10 stale and still carrying S0; synced/removed.

## M2 "re-scan ready" — broker 1.3.0 (T8–T10 + T22)

Permissions frontmatter, documentation completeness, `SECURITY.md`, plus T22 `--session-key` wake routing (kept in after the live registry showed `main.sessionKey` was already load-bearing). Findings fixed pre-commit: hardcoded Discord channel id in the notifier default (public repo), `network: []` made false by the notifier hook, pytest sending 40 live Discord messages per suite run (`CLAW_NO_NOTIFY` in conftest). ClawHub re-submission published 2026-08-08.

## Messaging incidents (July–Aug 2026) — why delivery is deterministic

- **July 26 "Reactive Mirror"**: a hook in the broker fired an *agentTurn* cron per `return`/`resolve` with `delivery_mode: announce` → duplicate posts, and on a fallback model 3× posts to a **typo'd channel id** (a digit transposition of the #scheduling channel id) produced by the LLM at send time. Fix direction: broker returns to pure state+ledger; mirroring is a deterministic `command` cron running the observer; channel ids live in state files, never typed by a model.
- **Aug armed double-post**: two readers kept two dedup models — `finalize` recorded `delivered_ids` without advancing the cursor, `process` advanced the cursor without checking `delivered_ids`. A cron job broken since 08-10 froze the cursor at 107/131 while the hook delivered 5 bottles past it; repairing the cron would have re-posted all 5. Defused by cursor edit + making `process` consult `is_delivered()`. The structural fix (one cursor, one dedup) is R2's reader merge.

## M3 "trustworthy routing" — broker 2.0.0 (T14/T15/T12/Q9)

Milestone order swapped M3↔M4 on live-ledger evidence (0/46 bottles stranded, but 6/46 authority violations and 16 registry misses). Shipped: canonical agent identity with aliases (`canon()`, `resolve_agent()`, absorb/merge in `register`, `^agent:[a-z0-9_-]+$` warn-not-refuse); authority enforcement (`forward`/`return` require holder, `resolve` requires creator + empty stack, `cancel` requires creator; `--force` ledgered as `authority-override`); depth/cycle guards (`MAX_STACK_DEPTH=8`, `--allow-cycle`); observer display names from the registry. One bug found by smoke test, not suite: `forward --to ECHO` recorded the alias as holder, so the canonical agent was refused its own return — `agent_key()` now resolves through the registry before recording or comparing (`de4aeba`). Live registry migrated 12→9 entries, ledger resolution 200→215 of 216. Suite 93 passed / 1 xfailed.

## ADR-001 Phase 1 + T23 + rename (late Aug)

Two skills, one repo; split writer vs reader (see the ADR for options/rationale). Combine landed at `34013ae`; suite repointed, all `pytest.skip` sibling paths deleted, `tests/contract/` enumerates writer event types from the AST and asserts a renderer for each; CI on push. T23 (`1aa4174`) moved the notifier into the reader, making the broker's `network: []` true. interagent-queue **1.3.0** published 2026-08-28 (`913f8b2`): cursor fail-closed, honest declarations, deprecation notice pointing at miab-observer; also ended the host-username exposure public since 1.2.0 (2026-07-22). Rename to **miab-observer** at `67dc035` (git `R` renames; state filenames deliberately unchanged). **2.0.0 published for both skills 2026-08-29 from `d31f969`.**

## Provenance notes that settle old arguments

- Git tag dates are unreliable (history reconstructed ~08-19); the ClawHub listing is authoritative for publish dates.
- The cursor-reset replay bug was live ~5 weeks, not a regression; the env under-declaration was new, not live (1.2.0 shipped no `permissions:` block).
- Old CHANGELOG entries keep the `interagent-queue` name — they record what was actually published.
- The Discord channel id that shipped in broker 1.3.0's notifier default is an **identifier, not a credential**; the hazard was misdirected delivery, remediated by requiring `CLAW_CLOSED_TARGET` (fail closed) + T23.
- ADR-001's "ClawHub serves 1.1.1" went stale on 2026-08-08 when 1.3.0 was published.
