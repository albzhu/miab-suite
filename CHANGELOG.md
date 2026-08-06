# Changelog

All notable changes to the `miab-broker` skill are recorded here.

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
