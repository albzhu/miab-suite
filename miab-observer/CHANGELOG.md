# Changelog

All notable changes to the `miab-observer` skill are recorded here.

**This skill was published as `interagent-queue` through 1.3.0** and renamed at 2.0.0. Entries
for 1.3.0 and 1.2.0 keep the old name throughout: they record what was actually published under
it. Renaming them retroactively would falsify the provenance the 1.2.0 entry exists to establish.

This file starts at 1.3.0. Version **1.2.0** was published to ClawHub on **2026-07-22** from a
working copy that was not under version control — `interagent-queue` only entered git with the
repository combine (ADR-001 Phase 1, 2026-08-26), whose earliest commit postdates that release.
The 1.2.0 section below was therefore reconstructed by diffing the published package
(`interagent-queue-1.2.0.zip`, sha256 `8865544e…9ef0`) against the tree, not from history.

## 2.0.1 — "Notifier hardening"

A patch release, and only the message sink changes: `scripts/notify_closed_bottles.py`, the one
piece of this skill whose output leaves the machine, and `scripts/notify_closed_dryrun.py`, which
shares its code. `miab_observer.py` (the log sink) is untouched. Every fix below answers a finding
that ClawHub's scanners raised against the published 2.0.0 package, except the ones marked as coming
from the review of this release's own code. Whether the scanners now rate 2.0.1 differently is
something only a re-scan of the published package can show; this entry says what the code does now and
how it was checked.

### What changes for existing installs

Read this before upgrading a host that runs the notifier from cron.

- **No backfill on first run.** A missing `closed_bottle_state.json` used to mean cursor 0, so the
  first `process` (and the first `on`, `off` or `finalize`, which created the same cursor-0 state)
  posted every closed bottle in the ledger. Now a missing state file starts at the **end** of the
  ledger: `process`, `on`, `off` and `finalize` all record the current ledger length as the cursor,
  post nothing, and say so in the status output. `finalize <cid>` is still how you post one older
  bottle on demand.
- **On a fresh install, a bottle that closes before the first run that sees a ledger is not posted.**
  With no state file and a missing or empty ledger, `process` records nothing (it does not create a state
  file), so the first `process` run that sees a non-empty ledger starts at *that* ledger's end. Run `on`
  first and the gap closes: `on` records the ledger start (cursor 0). **This is deliberate, and `process`
  will not do it for you**: recording cursor 0 whenever the ledger is empty would backfill the entire
  history if `CLAW_LEDGER` was mistyped at first and corrected later (for the same reason, run `on` only
  once `CLAW_LEDGER` is right). The `process` status message for that case now says it, and SKILL.md §3a
  states it in the first-run section and in the table.
- **A corrupt state file, or a truncated ledger, now exits `1`.** Before, an unreadable or invalid
  state file was silently replaced with cursor 0 and an empty `delivered_ids`, and a cursor beyond the
  ledger was silently reset to 0; both re-posted every closed bottle in the ledger. Now the notifier
  exits `1` with `{"ok": false, ...}` on stderr, delivers nothing and leaves the file untouched. **A cron
  job running it will start reporting that exit code; that is the intent.** SKILL.md §3a lists each
  case and how to recover. `render` and `notify_closed_dryrun.py` need no state and keep working when
  the file is damaged.
- **Your existing state file still loads.** The new `ledger_head` key is optional. The first 2.0.1 run
  adopts the ledger's fingerprint and continues from your cursor. Two edge cases: a 2.0.0 file whose
  cursor is beyond the ledger's length exits `1` ("ambiguous": truncation and the broker's rotation
  look the same without a fingerprint), with a remedy in the error; and a 2.0.0 file whose cursor is
  still `0` is indistinguishable from a legitimate one, so its first 2.0.1 run still posts the ledger
  from line 0.
- **A rotated ledger is followed, not rewound.** The broker rotates by renaming `ledger.jsonl`, which
  leaves a cursor beyond the new file's length. A different `ledger_head` now means "new ledger": read
  it from line 0, with `delivered_ids` preventing repeats. The same cursor with the *same* head is
  truncation, and exits `1`.
- **Messages look slightly different.** `@` and `<` in ledger text are followed by U+200B, `](` is
  split, control characters are gone, the bottle id and every reason are now capped and cleaned (the
  reasons were not before), and a long history ends with `... N more history line(s) omitted`. No
  message exceeds 1900 UTF-16 code units (so none exceeds 1900 characters either); a message heavy in
  emoji, which count as two units, loses more history lines than its character count alone would cost.
- **Small command changes.** `peek` now leaves out bottles already in `delivered_ids`, so it shows
  what `process` would send, and refuses a truncated ledger as `process` does. `status` gains
  `state_present`, `ledger_lines` and `ledger_head`. `on` checks `CLAW_CLOSED_TARGET` before it writes.
- **A failed send makes `process` exit `1`.** In 2.0.0 a send that failed (the `openclaw` CLI exiting
  non-zero, or not being runnable) parked the cursor on that bottle and `process` still exited `0`, so
  a bottle whose send could never succeed held up every bottle behind it while cron saw success on
  every run. Now `process` stops at the first failed send exactly as before (cursor on that bottle,
  nothing after it sent, earlier successes recorded), prints its usual JSON summary on stdout with
  `"ok": false`, `"delivered": false` and an `error` naming the bottle, and exits `1`. **A cron job
  running the notifier will start reporting that exit code when a send fails; that is the intent.**
  Every other `process` outcome still exits `0`, and its JSON gains `"ok": true`.
- **No new environment variables, paths or permissions.** The `permissions` block is unchanged.

### Fixed

- **State and cursor could re-post the whole ledger** — A.I.G `T09` ("Malformed notifier state or
  ledger truncation can replay previously delivered messages") and the matching ClawScan `T09`.
  `load_state()` swallowed every exception and returned cursor 0; `process` and `collect_new()` reset a
  cursor beyond the ledger to 0. Now: a missing state file is the only fresh start (and starts at the
  ledger end); a present but unusable one — unreadable, not JSON, not an object, `last_processed_line`
  not a non-negative integer (booleans rejected), `delivered_ids` not a list of strings, `enabled` not a
  boolean, `ledger_head` not a SHA-256 digest — fails closed in the shape `miab_observer.py` uses; and one
  function, `reconcile_cursor()`, decides how the cursor relates to the ledger for both `process` and
  `peek`. Checked by `tests/test_notifier_state_and_cursor.py`, which drives the notifier as a
  subprocess against a throwaway `CLAW_HOME` and a stand-in `openclaw` that records what it is asked to
  send (every unusable-state case × `process`, `on` and `finalize`; every row of the cursor table; delivery
  failure and retry).
- **Ledger text was posted without neutralising mentions** — A.I.G `T09` ("Untrusted ledger content is
  delivered to Discord without neutralizing mentions") and the matching ClawScan `T09`. One function now
  cleans every ledger-derived string (id, task, result, every reason, agent names, unknown event names)
  and caps it; the whole message is capped. Checked by `tests/test_notifier_chat_text.py` (field ×
  payload for `@everyone`, `@here`, `<@id>`, `<@!id>`, `<@&id>`, `<#id>` and a masked link, across
  resolve, cancel and fail, history lines and agent names), asserting on the `--message` argument the
  stand-in `openclaw` received. **Not checked: how Discord renders the result**, which needs a live send.
- **Dynamic code execution in the dry-run script** — static analysis `suspicious.dynamic_code_execution`
  (critical, `notify_closed_dryrun.py` line 23 in 2.0.0). The script loaded the notifier through
  `importlib` and `exec_module()`; it is now `import notify_closed_bottles`, and
  `tests/test_notifier_dryrun.py` asserts that neither script contains `exec_module`, `eval(` or `exec(`
  and that the dry run prints the same text a real delivery sends.
- **Unredacted ledger text leaves the machine** — ClawScan `SQP-2` (and the SkillSpector finding of the
  same id). **Documented, not removed**: task, result and reason still post, by decision, with no new
  environment variable and no metadata-only mode. SKILL.md §3a and `skill-card.md` now state exactly
  what is posted (bottle id, task, result, reason, agent names, model names, per-hop history), that none
  of it is redacted, what is neutralised, and what each fail-closed exit means.
- **Wording:** SKILL.md and the `target_channel()` docstring called a hardcoded channel id "a secret in
  committed text". It is an identifier, not a credential; the hazard of a default target is misdirected
  delivery. Corrected in both places.
- **A failed send was invisible to cron** — from the review of this release's code, not a scanner
  finding. `process` now exits `1` on the first failed send (see "What changes for existing installs").
  Checked by `tests/test_notifier_delivery.py`: a send that fails for the first, a middle and the last
  bottle of a batch (exit `1`, the summary names the bottle, nothing behind it is attempted, the cursor
  is on its end record, the next run sends it and the rest once each), a send that never succeeds
  (exit `1` on every run), the CLI missing from `PATH`, and `"ok": true` on every other outcome.
- **A crash or kill mid-batch re-posted the whole batch** — from the review of this release's code, not
  a scanner finding. `process` saved its state once, after the last send, so a process killed between a
  send and that save posted every bottle of the batch again on the next run. It now saves after every
  successful send (the id in `delivered_ids`, the cursor just past that bottle's end record,
  `ledger_head`), before it attempts the next, and once more when the batch ends. Writes stay atomic, and
  the file, its name and its existing keys are unchanged. **At most one bottle can still be re-posted:
  the one whose send had completed when the process died, before its save.** Checked by
  `tests/test_notifier_delivery.py`, in which the stand-in `openclaw` SIGKILLs the notifier during the
  send for the first, second and third bottle of a batch; the test reads the state left on disk, runs
  `process` again, and counts what was posted.
- **The 1900 cap was counted in code points, not UTF-16 units** — from the review of this release's
  code, not a scanner finding. `len()` counts code points, and an emoji is one code point but two UTF-16
  code units: a bottle whose task, result, reason, agent names and history were all emoji came out at
  1894 characters and 3382 units. If Discord or `openclaw` counts units, such a message would be
  refused on every attempt, and the cursor would stay on that bottle. The whole-message limit is now
  measured in UTF-16 code units (`utf16_units()`, never fewer than the code-point count, so it holds
  under either count) everywhere `_fit_report()` enforces it: whether the message fits, the room kept
  for the omitted-lines marker, and the last-resort cut, which trims whole code points so it cannot
  leave a lone surrogate. The per-field caps (task 300, result 400, reason 300, names 64) stay in
  characters, and a message that already fit with ordinary text is unchanged. Checked by
  `tests/test_notifier_chat_text.py`: all-emoji resolved, cancelled and failed bottles through the
  real send path, the exact 1900-unit boundary, and the last-resort cut driven directly, because no
  ledger reaches it while the field caps hold. **Not verified: which way Discord or `openclaw` actually
  counts.**

### Not addressed

- **The log sink's cursor rewind.** `miab_observer.py` still resets a cursor beyond the ledger to 0.
  Left alone on purpose until R2 merges the two cursors.
- **Two separate cursors.** `queue_state.json` and `closed_bottle_state.json` remain independent.
- **No redaction.** Nothing detects or removes secrets in ledger text before it is posted.
- **The `Hops:` line** counts the bottle's ledger lines, not delegation edges.
- **File modes.** The state file is still written at the ambient umask (the broker has 0700/0600; the
  observer does not yet).
- **Delivery is exactly-once only up to a one-bottle window.** A send that completes in the instant
  before the process dies is not yet recorded, so that one bottle is posted again on the next run.
- **A bottle whose send never succeeds still holds up the bottles behind it.** Delivery stays in
  ledger order and nothing skips a bottle automatically; `process` now exits `1` on every run until
  the send works, which is how it gets noticed.
- **Neutralisation is text-level and covers mentions and masked links only.** Bare URLs and other
  markdown still render.

## 2.0.0 — "miab-observer"

### Changed

- **Renamed from `interagent-queue` to `miab-observer`.** The old name described a queue; the
  skill is an observer over the broker's ledger and never queues anything. `miab-observer` also
  pairs it with `miab-broker`, which it cannot run without, and matches that skill's 2.0.0.

  **This is a breaking change and the reason for the major bump.** Skill identity is keyed on the
  frontmatter `name`, so an install of `interagent-queue` cannot become `miab-observer` by
  updating — it has to be installed deliberately. `interagent-queue` 1.3.0 was published as a
  final deprecation release carrying the migration notice, because it was the only channel that
  could reach the existing install base.

- **`scripts/interagent_queue.py` → `scripts/miab_observer.py`.** This is the change most likely
  to bite: a cron entry whose `--command` points at the old path keeps working until
  `interagent-queue` is removed, then fails silently. Update cron before removing the old skill.

### Not changed, deliberately

- **All on-disk state keeps its existing names and locations.** `queue_state.json`,
  `closed_bottle_state.json`, `$CLAW_HOME/logs/interagent-queue.log` and the broker's
  `ledger.jsonl` are keyed on `CLAW_HOME` / `LYRA_WORKSPACE`, never on the skill name, so the
  cursor and dedup state carry across the rename untouched. **Nothing replays and nothing is
  re-delivered.**

  This was not free to leave alone — it is why the log file still says `interagent-queue`.
  Renaming the state files would have reset the cursor, and a reset cursor replays the whole
  ledger into the log: exactly the bug 1.3.0 was released to fix. Renaming
  `closed_bottle_state.json` would have been worse, re-posting every closed-bottle summary to the
  configured chat target. A tidier filename is not worth either. Set `CLAW_QUEUE_LOG` to rename
  the log yourself.

- **`AGENT_MAP`, the renderers and the ledger contract are untouched.** 2.0.0 is a rename, not a
  rewrite. The broker floor stays at miab-broker 2.0.0 for the reasons in Prerequisites.

## 1.3.0 — "Registry identity, and a cursor that refuses to rewind" — final release as `interagent-queue`

> **This skill is renamed to `miab-observer` and continues there at 2.0.0.** 1.3.0 is the last
> release published as `interagent-queue`. Skill identity is keyed on the frontmatter `name`, so
> installs cannot follow a rename — `miab-observer` must be installed deliberately, and the
> script moved from `scripts/interagent_queue.py` to `scripts/miab_observer.py`, so cron
> `--command` lines need updating. On-disk state is keyed on `CLAW_HOME` / `LYRA_WORKSPACE` and
> carries over untouched. Migration steps are at the top of SKILL.md.
>
> Entries below this line, and the 1.2.0 entry, describe releases that shipped as
> `interagent-queue`. They are left under that name deliberately: they are a record of what was
> published, not of what the skill is called now.

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

- **The closed-bottle message sink now lives here** (ADR-001 T23). `notify_closed_bottles.py` and
  `notify_closed_dryrun.py` moved from `miab-broker/scripts/`, where they had become tracked files
  during the repository combine. A delivery sink is a reader concern, and while the broker CLI
  never called them, a package containing a script that shells out to `openclaw message send`
  cannot honestly declare `network: []` — the broker's scoping of that claim to the CLI lived in
  prose, which no scanner reads. The broker's declaration is now true without qualification, and
  this skill declares the egress instead. Documented in SKILL.md §3a.

  Carried over from the broker's changelog, since the script moved: **`CLAW_CLOSED_TARGET` is
  required** and the notifier fails closed with `{"ok": false, ...}` and a non-zero exit when it
  is unset. The previous hardcoded channel-id default is gone — it was both a secret in committed
  text and a way to mistarget delivery on a host that never configured the notifier.

  This is a relocation, not the merge. The two sinks still keep separate cursors and separate
  dedup state; unifying them is ADR-001 item 7, still Phase 2. `notify_closed_dryrun.py` is still
  a separate script rather than a `--dry-run` flag (item 10).

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
- **A `permissions` block in the frontmatter.** 1.2.0 declared none. Every environment variable
  either script reads is listed — `CLAW_HOME`, `LYRA_WORKSPACE`, `CLAW_LEDGER`,
  `CLAW_QUEUE_STATE`, `CLAW_QUEUE_LOG`, `CLAW_REGISTRY` for the log sink, and
  `CLAW_CLOSED_TARGET`, `CLAW_CLOSED_STATE`, `CLAW_CLOSED_ACCOUNT` for the message sink — along
  with the files read and written. A partial declaration would be worse than none: it is an
  assertion a scanner can falsify.
- **A non-empty `network` declaration**, covering the message sink's delegated egress. The
  notifier opens no socket itself; it shells out to `openclaw message send`, whose transport and
  destination are configured outside this skill. Declared anyway, because the skill does cause
  egress. The log sink — the default path, and all of `interagent_queue.py` — still touches
  nothing but the local filesystem.
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
