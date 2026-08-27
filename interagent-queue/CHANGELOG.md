# Changelog

All notable changes to the `interagent-queue` skill are recorded here.

This file starts at 1.3.0. Version **1.2.0** was published to ClawHub on **2026-07-22** from a
working copy that was not under version control — `interagent-queue` only entered git with the
repository combine (ADR-001 Phase 1, 2026-08-26), whose earliest commit postdates that release.
The 1.2.0 section below was therefore reconstructed by diffing the published package
(`interagent-queue-1.2.0.zip`, sha256 `8865544e…9ef0`) against the tree, not from history.

## 1.3.0 — "Registry identity, and a cursor that refuses to rewind"

First release since the skill entered version control, and the first published from the combined
`miab-broker` + `interagent-queue` repository.

### Fixed

- **A corrupt state file no longer replays the entire ledger.** `load_state()` swallowed every
  exception and fell through to the same `{"enabled": false, "last_processed_line": 0}` default
  it uses for a genuine fresh start. A truncated or malformed `queue_state.json` therefore
  rewound the cursor to 0 without a word, and the next `process` wrote every ledger record that
  had ever existed into the log. The failure mode duplicated the output this observer exists to
  produce, which is worse than not running.

  A missing state file is still a fresh start. A present-but-unusable one — unparseable, not a
  JSON object, or carrying a `last_processed_line` that is not a non-negative integer — now exits
  `1` with `{"ok": false, ...}` on stderr, rewinds nothing, and writes nothing. Recovery is the
  operator's deliberate choice: repair the file, or delete it to accept a full replay. Documented
  in SKILL.md §4.

  Present in 1.2.0 and every install since 2026-07-22.

### Changed

- **The broker's agent registry is now authoritative for display names** (Q9). `who()` resolves
  through `agent-registry.json` first, falling back to this file's built-in `AGENT_MAP` only for
  agents that have never been registered, and lookups are case-folded to match the broker's
  canonical form. `AGENT_MAP` had duplicated the persona↔function mapping the registry owns since
  broker T14, and the copy silently fell back to the raw name on a miss — which is why `SPECTRE`
  and `ECHO` rendered inconsistently. Adds one env var, `CLAW_REGISTRY`, and one read-only file
  read; the registry is cached per process and never mutated.
- **Install paths in the documentation are no longer hardcoded.** The command examples said
  `python3 Skills/interagent-queue/scripts/interagent_queue.py`, which is correct only for one
  install layout. They now use `<interagent-queue>/scripts/interagent_queue.py`, resolved against
  wherever the skill is installed.
- **§3 no longer names host home directories.** The multi-platform note illustrated itself with
  two literal `/Users/<name>` paths. The point it was making — that every location resolves from
  the environment and nothing is hardcoded to a host — is now made without them.

### Added

- **Renderers for `authority-override` and `corrupt`.** An event type the writer can emit but the
  reader cannot render returns `None` from `format_event()` and is dropped by `collect_new()`, so
  an unrendered type is *invisible* rather than broken — no ordinary test catches it. `corrupt`
  shipped that way in broker 1.2.0; `authority-override` (broker 2.0.0, T15) came within a backlog
  note of repeating it. The repository's `tests/contract/` now derives the writer's event list from
  its own AST and asserts a renderer exists for each, so this class of gap fails CI instead of
  going quiet.
- **A `permissions` block in the frontmatter.** 1.2.0 declared none. All six environment variables
  the script reads are listed — `CLAW_HOME`, `LYRA_WORKSPACE`, `CLAW_LEDGER`, `CLAW_QUEUE_STATE`,
  `CLAW_QUEUE_LOG`, `CLAW_REGISTRY` — along with the files read and written, and `network: []`.
  A partial declaration would be worse than none: it is an assertion a scanner can falsify.
- **A declared minimum `miab-broker` version: 2.0.0** (Q7). The floor is set by identity, not by
  the ledger format — the `displayName` and `aliases` fields `who()` reads were added by broker
  T14 in 2.0.0, and against an older broker every agent silently falls back to `AGENT_MAP`, which
  is the inconsistency the registry lookup exists to fix.
- **`skill-card.md` is now in the repository.** It shipped in the 1.2.0 package but existed
  nowhere in source, so publishing from a clean checkout would have dropped or regressed it.
- **This changelog.** Its absence is why the 1.2.0 baseline had to be recovered by downloading
  the published package and diffing it.

## 1.2.0 — published 2026-07-22

Reconstructed from the published package; no source history exists for this release or earlier.

Ledger observer over `miab-broker`'s append-only callback ledger, with a once-only cursor, the
`on` / `off` / `status` / `process` / `peek` command surface, `AGENT_MAP`-based display names, and
renderers for `create`, `forward`, `return`, `resolve`, `cancel` and `fail`. State at
`$LYRA_WORKSPACE/state/callbacks/queue_state.json`; log at `$CLAW_HOME/logs/interagent-queue.log`.
