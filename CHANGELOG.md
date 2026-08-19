# Changelog

All notable changes to the `miab-broker` skill are recorded here.

## 1.3.0 — M2 "Re-scan ready" (2026-08-19)

Documentation and metadata milestone (tasks T8–T10 of the execution backlog), plus one additive
routing feature (T22). The release exists to make the skill's authority, security model, and full
command surface explicit to operators and to ClawHub's scanners.

The only behaviour change is `--session-key` (below). It is additive: a registry entry without a
`sessionKey` produces byte-for-byte the same `wake`/`return` output as 1.2.1.

### Added

- **`register --session-key`, and `sessionKey`-aware wake routing** (T22). A registry entry may
  now carry an exact `sessionKey` that overrides the agent's default wake lane, so a bottle
  completion resurfaces in a specific chat session rather than the agent's background lane. When
  an entry has one, `register`, `wake` and `return` emit
  `sessions_send(sessionKey=…, message=…)` instead of `cron(action=wake, agentId=…, text=…)`, and
  echo the key back as `sessionKey` / `wake_sessionKey` alongside the unchanged `agentId`.
  Entries without a `sessionKey` are untouched — the `cron(...)` instruction and the output shape
  are exactly as before. Routing is centralised in a single `wake_route()` helper so `wake` and
  `return` cannot drift apart. Covered by `tests/test_t22_session_key.py`, which asserts both the
  overridden and the unchanged path.

- **Declared permissions in `SKILL.md` frontmatter** (T8). A `permissions:` block now states the
  environment variables read (`CLAW_HOME`, `CALLBACK_TTL_MIN`), the exact file read/write globs,
  and that the skill makes no network calls — addressing SkillSpector **LP3** (confidence 0.94),
  which flagged that a skill enabling persistent state manipulation and wake-routing changes
  declared only `name` and `description`. The declaration matches what the code already enforces
  via path containment; it is a description of existing behaviour, not a new control.
- **`wake` and `show` are documented** (T9). Both were entirely absent from §2 and the Quick
  Reference despite `wake` being how dispatch actually happens — every other command's `next_step`
  points at it. An agent reading only the skill would hand-roll the `cron` call and get the
  `agentId` wrong.
- **`§3` now documents the envelope schema** and the full file inventory, including the
  `archive/` and `archive/corrupt/` trees added in 1.2.0, and notes the `ledger.jsonl` field names
  as a compatibility contract with the sibling `interagent-queue` skill.
- **New `§4 Security Model`** stating the trust boundary, what is enforced, and — explicitly —
  what is not: unverified `--from`, no integrity/replay protection, no concurrency safety,
  plaintext unbounded retention. Includes the instruction not to place secret values in
  `--task`/`--summary`/`--result`, since those are persisted and copied into inter-agent
  `dispatch_message` text.
- **Agent-name key in `§1`.** The architecture diagram and the examples throughout use persona
  names (LYRA, SPECTRE, Cinder, ECHO …) with no explanation of who they are or how they relate to
  the functional ids (`main`, `planner`, `coder`, `reviewer` …) that the broker actually routes on.
  Added a mapping table making the distinction explicit, noting the personas are illustrative
  display names from the reference deployment rather than anything the skill requires, and that
  `agent-registry.json` is the routing source of truth with exact-match lookup — the reason an
  agent returning as `ECHO` rather than `reviewer` misses the registry.
- **New `§6 Troubleshooting`** mapping every error introduced in 1.2.x to its cause and fix.
  Behaviour changes such as strict id validation, `CLAW_HOME` ownership checks, and resume-file
  containment were previously enforced but undocumented, so operators met them only as errors.
- **`SECURITY.md`** (T10) with reporting instructions, trust boundary, enforced controls, known
  limitations, and operator guidance.

### Changed

- `VERSION` `1.2.1` → `1.3.0`.
- `tests/conftest.py` now sets `CLAW_NO_NOTIFY=1` in the subprocess environment. The suite resolves
  around forty bottles per run; this guarantees no build of the CLI can turn that into outbound
  messages on a developer machine that happens to have a sender on `PATH`.
- §2's preamble rewritten — the previous version was a 90-word single sentence in a file agents
  read on every invocation.
- §5 (reaper) now carries an explicit warning against scheduling on the default 120-minute
  threshold without measuring first, since real delegation latency is bimodal and a single global
  TTL will destroy legitimate long-running work.

### Not in this release

- **The end-state notifier is deliberately held back.** `scripts/notify_closed_bottles.py` tails
  the ledger for `resolve`/`cancel`/`fail` and posts a bottle's history to a chat channel. A hook
  wiring it into `resolve`/`cancel`/`sweep --fail` was prototyped and removed again before this
  release: it makes an outbound network call, which contradicts the `network: []` permission
  declared above and the "makes no network calls" statement in `SKILL.md`; it blocks `resolve` on
  a subprocess, and inside `sweep`'s loop it blocks once per stale bottle. Shipping it means
  declaring the network capability honestly, making the call asynchronous, and gating it behind
  explicit opt-in. Tracked as T23.

## 1.2.1 — post-review fixes (2026-08-05)

Cleanup found by an independent post-implementation review of M1 (v1.2.0). No
new scope — same T1–T7 boundary as M1; nothing from T8 onward touched.
See `docs/miab-broker/M1-punchlist-completion.md` for the full report.

### Fixed

- **`_validate_root()`'s mode check was numeric, not a bitmask.** `if mode >
  0o700` let any mode whose owner triad was < 7 slip through regardless of
  group/other bits — `0o550` (group-readable) and `0o505` (world-readable)
  were both silently accepted. Now `if mode & 0o077`, refusing any
  group-or-other-accessible root, with the error message and docstring
  reworded to match. `tests/test_t4_root_validation.py` only probed `0o777`
  and `0o700`; added parametrized boundary cases for `0o750`, `0o550`,
  `0o540`, `0o505` (all refused) alongside the existing `0o700` (accepted).
  `claw-callback.py`, `tests/test_t4_root_validation.py`.
- **`SKILL.md`'s command examples were still CWD-relative.** T2 made the code
  emit absolute paths (`SELF = Path(__file__).resolve()`), but the docs still
  showed `python3 Skills/miab-broker/scripts/bin/claw-callback.py`, which only
  resolves if the reader's cwd happens to be the workspace root. Checked
  `~/.openclaw/scripts/claw-callback.py` (the pre-M1 canonical path) —
  no deployed copy exists there. Reworded the "Canonical location on the live
  host" claim (there isn't one fixed absolute path across installs) and
  replaced all 9 example invocations with a `<miab-broker>` placeholder the
  reader resolves once, noting every `next_step` the CLI itself prints is
  already an absolute path. `SKILL.md`.
- **The `corrupt` ledger event (added in T6) was invisible to the observer.**
  `interagent_queue.py`'s `format_event()` returned `None` for it, so
  quarantine notices — the whole point of quarantining instead of silently
  skipping a bad envelope — never reached the Discord-facing log. Added a
  `corrupt` branch matching the existing style, and extended
  `test_ledger_schema_compat.py` with a case that appends a `corrupt` record
  to a scratch ledger and asserts `interagent_queue.py peek` renders it.
  `interagent-queue/scripts/interagent_queue.py`,
  `tests/test_ledger_schema_compat.py`.

- **The `VERSION` constant didn't match this changelog.** It was the float
  `1.2` while the released version was `1.2.1`, so the only machine-readable
  version the CLI carries disagreed with the human-readable one — and a float
  can't express a patch level at all. Now the string `"1.2.1"`. `VERSION` has
  exactly one consumer (the `version` field stamped onto each envelope) and is
  never compared numerically, so this is inert at runtime; envelopes written
  from here on carry `"version": "1.2.1"` rather than a number. Pre-existing
  envelopes stamped `1`/`1.1`/`1.2` still load — nothing reads the field.
  `claw-callback.py`.

### Chore

- Added `miab-broker/.gitignore` (`__pycache__/`, `*.pyc`, `.pytest_cache/`)
  and removed the `.pytest_cache/`, `tests/__pycache__/`, and
  `scripts/bin/__pycache__/` directories that had accumulated untracked —
  build artifacts inflate the ClawHub package and perturb its hash.

## 1.2.0 — M1 "Exploit closed" (2026-08-05)

Security remediation milestone. Closes the arbitrary-file primitive reported
in `docs/miab-broker/miab-broker-security-remediation.md` (S0–S8) and
implements tasks T1–T7 of `docs/miab-broker/miab-broker-execution-backlog.md`.
See `docs/miab-broker/M1-completion.md` for the full task-by-task report.

**This release is behaviour-breaking.** Callback ids, `CLAW_HOME` roots, and
`--resume-file`/`--resume-json` inputs that were previously accepted
silently are now rejected. Update any automation that relied on the old
permissive behaviour.

### Security

- **[T1 / S0 — HIGH]** `--id` is now regex-validated (`^cb-\d{14}-[0-9a-f]{6}$`)
  and every resolved path is confined to the callback state root (and to
  `archive/` for archived envelopes). Previously an unvalidated id let a
  caller read, overwrite, or delete arbitrary `.json` files reachable by the
  process — including files outside `$CLAW_HOME` entirely.
- **[T4 / S8 — HIGH]** `$CLAW_HOME` is now validated on startup: the resolved
  root must be owned by the current uid and mode `<= 0700`, or the process
  refuses to run. A first run against a not-yet-existing root is still
  permitted (state is created under the process umask). Closes a routing-
  hijack primitive where a poisoned `CLAW_HOME` env var could redirect
  `agent-registry.json` and control where `wake` events are delivered.
- **[T5 / S2 — MEDIUM]** `os.umask(0o077)` set at process entry;
  `state/callbacks/` and `archive/` (and its subdirectories) are explicitly
  `chmod 0700`; envelope, registry, and ledger files are `chmod 0600` before
  being made visible via atomic replace. State created under a permissive
  ambient umask is no longer world-readable.
- **[T7 / S3 — MEDIUM]** `--resume-file` is confined to `$CLAW_HOME` unless
  `--allow-outside` is passed, capped at 64 KB, and the resume object is
  schema-validated (`summary`/`steps`/`expects`/`integrate` only — unknown
  keys rejected). Closes a file-to-agent exfiltration path where any
  process-readable JSON file could be laundered into a callback envelope and
  forwarded to another agent.

### Fixed

- **[T2 / F1 — BLOCKING]** Every emitted command path (`create`'s and
  `return`'s `next_step`, `wake_message()`, `cmd_wake`'s registry-miss
  fallback) now derives from `Path(__file__).resolve()` instead of a
  CWD-relative or hardcoded `~/.openclaw/scripts/...` path. An agent
  following a `next_step` it was just handed no longer gets
  "No such file or directory" from any working directory. `SKILL.md`'s
  examples are corrected to match the real script location
  (`scripts/bin/claw-callback.py`).
- **[T6 / S7 — MEDIUM]** Failures now fail closed instead of silently or
  loudly-but-uselessly:
  - Malformed `--resume-json`/`--resume-file` input and corrupt envelopes on
    disk now produce a structured `{"ok": false, "error": ...}` on stderr
    with a non-zero exit, instead of a raw traceback leaking absolute paths
    into agent context.
  - `wake` on a registry miss now exits non-zero (previously exited 0 with
    `"ok": false`, which no wrapper or scheduler could detect).
  - `list` and `sweep` no longer swallow corrupt/inconsistent envelopes with
    a bare `except: continue`. They're quarantined to
    `archive/corrupt/` with a `corrupt` ledger event and surfaced via a new
    `quarantined` count in both commands' output, instead of becoming
    invisible "immortal zombie" files.

### Added

- `Skills/miab-broker/tests/` — pytest regression suite (T3) covering every
  check above plus full happy-path regression (`create → wake → return →
  resolve` and the forward-chain variant), and cross-checked against the
  sibling `interagent-queue` skill's ledger parser. Includes an `xfail`-
  marked reproduction of the concurrent-writer envelope corruption gap,
  explicitly deferred to T11 (M3) rather than fixed here.

### Notes

- `VERSION` (the envelope schema-version field written into every envelope)
  is bumped `1.1` → `1.2` alongside the skill version. No envelope key was
  renamed or removed; the `ledger.jsonl` record schema is unchanged and
  remains compatible with `interagent-queue`'s parser (a new `corrupt` event
  type is additive — unrecognized event types are already ignored by that
  parser).
- Out of scope for this release, deferred to later milestones per the M1
  scope boundary: envelope locking / concurrency safety (T11), authority
  checks on `--from` (T15), agent aliases (T14), TTL and redelivery
  (T16/T17), HMAC integrity (T19), `stats`/`doctor` (T20), and the SKILL.md
  permissions/structure rewrite (T8/T9).

## 1.1.1 and earlier

Pre-dates this changelog. See `docs/miab-broker/miab-broker-security-remediation.md`
and `docs/miab-broker/miab-broker-feature-roadmap.md` for the audit and
review that motivated 1.2.0.
