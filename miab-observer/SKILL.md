---
name: "miab-observer"
description: "Observe the MIAB transaction ledger: render callback events to a human-readable log, and optionally post closed-bottle summaries to a chat target. The observer half of the MIAB pair; requires miab-broker. Formerly published as `interagent-queue`."
permissions:
  env: [CLAW_HOME, LYRA_WORKSPACE, CLAW_LEDGER, CLAW_QUEUE_STATE, CLAW_QUEUE_LOG, CLAW_REGISTRY,
        CLAW_CLOSED_TARGET, CLAW_CLOSED_STATE, CLAW_CLOSED_ACCOUNT]
  file_read:
    - "$CLAW_HOME/state/callbacks/ledger.jsonl"
    - "$CLAW_HOME/state/callbacks/agent-registry.json"
  file_write:
    - "$LYRA_WORKSPACE/state/callbacks/queue_state.json"
    - "$CLAW_HOME/logs/interagent-queue.log"
    - "$CLAW_HOME/state/callbacks/closed_bottle_state.json"
  network:
    # Indirect egress, and declared anyway. No socket is opened in this skill: the message
    # sink (scripts/notify_closed_bottles.py) shells out to `openclaw message send`, whose
    # transport and destination are configured outside this skill via CLAW_CLOSED_TARGET.
    # The log sink -- the default, and everything under `miab_observer.py` -- touches
    # nothing but the local filesystem.
    - "openclaw message send (delegated subprocess; destination set by CLAW_CLOSED_TARGET)"
---

> **Formerly `interagent-queue`.** This skill was published under that name through 1.3.0 and
> renamed here at 2.0.0. If you are migrating: the script is now `scripts/miab_observer.py`, so
> cron `--command` lines need updating, but **all on-disk state carries over untouched** — the
> cursor, dedup state, log and ledger are keyed on `CLAW_HOME` / `LYRA_WORKSPACE`, never on the
> skill name. Nothing replays and nothing is re-delivered. See CHANGELOG.md.

# MIAB Observer — Asynchronous Transaction Observer

This skill governs the transaction processing, formatting, and file-based logging for the **Message-in-a-Bottle (MIAB) LIFO Callback Stack**. It decouples the observer and human-readability layers from the core `miab-broker` protocol.

---

## Prerequisites

- **`miab-broker` skill, version 2.0.0 or later**: `miab-observer` operates strictly as an
  observer layer over `miab-broker`. `miab-broker` must be installed and initialized to produce
  the transaction ledger (`$CLAW_HOME/state/callbacks/ledger.jsonl`).

  The 2.0.0 floor is set by agent identity, not by the ledger format: `who()` resolves display
  names from the broker's `agent-registry.json`, and the `displayName` and `aliases` fields it
  reads were added by broker T14 in 2.0.0. Against an older broker the registry lookup finds
  nothing and every agent silently falls back to this file's built-in `AGENT_MAP` — which is the
  inconsistency (`SPECTRE` vs `ECHO`) that reading the registry exists to fix. The renderers are
  a weaker constraint: `authority-override` is a 2.0.0 event, but `corrupt` dates to broker
  1.2.0, so the renderers alone would not have forced 2.0.0.

---

## 1. What the Interagent Queue Observer Does

The observer (`scripts/miab_observer.py`) is a transaction monitor that tails the append-only callback events log (`state/callbacks/ledger.jsonl`). It parses events in real-time or via frequent interval sweeps, matches logical agent references (like `main`, `planner`, `coder`, or `reviewer`) with friendly icons, and formats them into clean, compact, human-readable log entries.

Transaction events are written directly to the observer log file (`$CLAW_HOME/logs/interagent-queue.log` by default, configurable via `CLAW_QUEUE_LOG`).

---

## 2. Invocations & Commands

The utility script `miab_observer.py` can be driven from the CLI to enable/disable sweeps, check cursor tracking status, or run isolated manual analysis.

Invoke it at `scripts/miab_observer.py`, resolved against wherever this skill is installed for you (written `<miab-observer>` below). There is no fixed absolute path that is correct across installs.

```bash
# Toggle logging sweeps
python3 <miab-observer>/scripts/miab_observer.py on
python3 <miab-observer>/scripts/miab_observer.py off

# Check cursor status, live state file, log file path, and target ledger
python3 <miab-observer>/scripts/miab_observer.py status

# Manually process and sweep all un-processed ledger records into the log file
python3 <miab-observer>/scripts/miab_observer.py process

# Peek at new ledger records inside stdout WITHOUT updating your cursor or writing to the log file
python3 <miab-observer>/scripts/miab_observer.py peek
```

---

## 3. Storage & State Management

To decouple concerns and ensure multi-platform flexibility (e.g. running under separate user accounts, home directories, or containers), all operational locations resolve dynamically relative to home environments — nothing is hardcoded to a host path:

- **State Document:** `$LYRA_WORKSPACE/state/callbacks/queue_state.json` tracks cursor indexing
  (`last_processed_line`) and live enabled status (overrideable via `CLAW_QUEUE_STATE`). If this
  file exists but cannot be parsed, the observer exits `1` rather than rewinding the cursor —
  see §4.
- **Active Ledger Source:** `$CLAW_HOME/state/callbacks/ledger.jsonl` (provided by `miab-broker`,
  overrideable via `CLAW_LEDGER`).
- **Agent Registry:** `$CLAW_HOME/state/callbacks/agent-registry.json` (read-only, provided by
  `miab-broker`, overrideable via `CLAW_REGISTRY`). Authoritative source for agent display names.
- **Target Log File:** `$CLAW_HOME/logs/interagent-queue.log` (overrideable via `CLAW_QUEUE_LOG`).
  **The default log filename deliberately still says `interagent-queue`.** Renaming it would
  start a second log beside your existing one and silently orphan the first, and it would break
  any log rotation or shipping already pointed at that path — for cosmetics. The 2.0.0
  migration promise is that on-disk state carries over untouched, and this is part of keeping
  it. Set `CLAW_QUEUE_LOG` if you want a different name.

---

## 3a. The Message Sink (`scripts/notify_closed_bottles.py`)

Relocated here from `miab-broker` by ADR-001 T23: the broker is the writer, and a delivery sink
is a reader concern. The move is what lets the broker declare `network: []` without scoping it
to one file in prose, and it is why this skill declares network at all.

`miab_observer.py` remains the default and touches nothing but the local filesystem. The
message sink is separate, cron-driven, and never invoked by the log sink. It is the only code in
either skill whose output leaves the machine, so read "What leaves the machine" before enabling it.

```bash
# Render what WOULD be sent, without sending or advancing any cursor. Reads no state file.
python3 <miab-observer>/scripts/notify_closed_dryrun.py
python3 <miab-observer>/scripts/notify_closed_dryrun.py --json
python3 <miab-observer>/scripts/notify_closed_dryrun.py <cid>

# Deliver closed-bottle summaries to CLAW_CLOSED_TARGET (`process` is the default command)
python3 <miab-observer>/scripts/notify_closed_bottles.py
python3 <miab-observer>/scripts/notify_closed_bottles.py peek             # what `process` would send; writes nothing
python3 <miab-observer>/scripts/notify_closed_bottles.py status           # cursor, target, state-file path
python3 <miab-observer>/scripts/notify_closed_bottles.py on               # enable delivery (and `off` to disable it)
python3 <miab-observer>/scripts/notify_closed_bottles.py render <cid>     # print one message; reads no state
python3 <miab-observer>/scripts/notify_closed_bottles.py finalize <cid>   # post one bottle now, exactly once
```

### What leaves the machine

Each bottle that reaches an end state (`resolve`, `cancel`, `fail`) is posted as one message to
`CLAW_CLOSED_TARGET` through `openclaw message send`. The message contains:

- the **bottle id**;
- the **task**, and the **result** (resolved bottles) or the **reason** (cancelled or failed ones);
- the **agent names** involved, and the **model names** behind them (each agent's primary model,
  from a map built into the script);
- the **per-hop history**: one line for every ledger record of that bottle (created, forwarded,
  returned, resolved, cancelled, failed, quarantined), including every `reason` those records carry.

**None of it is redacted.** Task, result and reason text is posted as the ledger holds it. If an
agent writes a secret, an internal prompt or someone's personal data into a bottle, it goes to the
chat channel. Keep such content out of ledger text, or leave this sink off. There is no
metadata-only mode and no switch that removes the bodies.

What is done to the text first, by one function applied to every ledger-derived string (bottle id,
task, result, every reason, agent names, event names):

- control characters are removed and whitespace is collapsed, so a value cannot forge a line of the
  report;
- U+200B (a zero-width space) is inserted after every `@` and every `<`, so `@everyone`, `@here`,
  `<@id>`, `<@!id>`, `<@&id>` and `<#id>` do not mention anyone;
- `](` is split, so `[text](url)` does not render as a masked link;
- each field is capped (task 300 characters, result 400, reason 300, agent and event names and ids
  64), and so is the whole message, at 1900 UTF-16 code units (a character outside the Basic
  Multilingual Plane, such as most emoji, counts as two). Units are never fewer than characters, so
  the cap holds whether the receiving end counts characters or units; a message that is mostly emoji
  therefore carries fewer than 1900 characters. When history lines are dropped to fit, the message
  says how many.

That is the whole of it. Bare URLs and other markdown still render, and the cleaning is text-level:
nothing is added to the `openclaw message send` call. It is tested against the exact text handed to
`openclaw`, not against a live channel, so how a given Discord client renders the neutralised text
has not been verified.

### Configuration

- **`CLAW_CLOSED_TARGET` is required and fails closed.** Unset, any command that would deliver exits
  `1` with `{"ok": false, ...}` and sends nothing. There is no default target. A channel id is an
  identifier, not a credential, so the reason is not secrecy: a baked-in default would aim every host
  that never configured this notifier at someone else's channel.
- **`CLAW_CLOSED_ACCOUNT`** is optional, passed through as `--account`.
- **Delivery state** lives at `$CLAW_HOME/state/callbacks/closed_bottle_state.json` (overrideable via
  `CLAW_CLOSED_STATE`), and is separate from the log sink's cursor. It holds the toggle, the cursor
  (`last_processed_line`), the ids already delivered (`delivered_ids`, newest 500), and `ledger_head`,
  the SHA-256 of the ledger's first non-empty line, which identifies the ledger the cursor belongs to.
  State files written by 2.0.0 have no `ledger_head`; they still load.
- **Egress is delegated, not direct.** The notifier opens no socket; it shells out to
  `openclaw message send`, whose transport and destination are configured outside this skill.

### First run, and when it exits `1`

**The first run starts at the ledger end.** With no state file, the first `process` records the
current ledger length as its cursor and posts nothing; its status output says so. Bottles that close
after that are delivered. `on`, `off` and `finalize` create a missing state file the same way, so none
of them leaves behind a cursor that a later `process` would backfill from. To post one older bottle,
run `finalize <cid>`.

A state file that exists but cannot be trusted, or a cursor that no longer fits the ledger, is never
"fixed" by starting over, because starting over re-posts every closed bottle in the ledger to chat.
The notifier stops instead, and changes nothing:

| Situation | What happens | How to recover |
|---|---|---|
| State file missing | First run: cursor set to the ledger end, nothing posted. | Nothing to do. |
| State file present but unusable: unreadable, not valid JSON, not an object, `last_processed_line` missing or not a non-negative integer, `delivered_ids` not a list of strings, `enabled` not `true`/`false`, `ledger_head` not a SHA-256 hex digest | **Exit `1`**, `{"ok": false, ...}` on stderr, nothing posted, the file left byte for byte as it was. | Repair it, keeping `last_processed_line` and `delivered_ids`, or delete it: the next run is then a first run (posts nothing), and `finalize <cid>` posts any bottle the gap skipped. |
| Cursor beyond the ledger's length, `ledger_head` matches the ledger | The ledger was truncated. **Exit `1`**, nothing posted. | Restore the ledger, or lower `last_processed_line` to at most its line count, or delete the state file. |
| `ledger_head` differs from the ledger's first line (any cursor) | The broker rotated (renamed) the ledger and started a new one. The new ledger is read from line 0, its `ledger_head` is recorded, and `delivered_ids` keeps recorded bottles from being posted twice. The status output says so. | Nothing to do. |
| 2.0.0 state file (no `ledger_head`), cursor beyond the ledger's length | Truncation and rotation look the same without a fingerprint. **Exit `1`**, nothing posted. | If the ledger was rotated, set `last_processed_line` to `0`; if it was truncated, set it to the ledger's line count; or delete the state file. |
| Ledger missing or empty | No-op; state untouched. | Nothing to do. |
| `CLAW_CLOSED_TARGET` unset | **Exit `1`**, nothing posted. | Set it. |
| A send fails during `process` (the `openclaw` CLI exits non-zero or cannot be run) | The batch stops at that bottle: the cursor is saved on it, so the next run retries it first, and nothing after it is sent. Bottles delivered earlier in the same run stay recorded. **Exit `1`**, with the usual JSON summary on **stdout** (not stderr, because it also lists what the run did deliver) carrying `"ok": false`, `"delivered": false` and an `error` that names the bottle. | Fix the send: the `openclaw` CLI, `CLAW_CLOSED_TARGET`, `CLAW_CLOSED_ACCOUNT`. The next run retries that bottle, then the rest. Until it succeeds the bottle holds up every bottle behind it, and every run exits `1`. |

`1` is deliberate: a cron `--command` job will report it, where a silent reset would not. This
includes a failed send during `process`, as `finalize` already did: a bottle whose send never
succeeds holds up the ones behind it (delivery stays in ledger order), and the exit code is what
makes that visible instead of looking like success on every run. Every other `process` outcome exits
`0` and prints a summary with `"ok": true`.

One thing the exit code does not cover: bottles that closed in a ledger the broker has since rotated
away, after the cursor but before the rotation, are not posted by the rotation path; to post one,
point `CLAW_LEDGER` at the archived `ledger.<timestamp>.jsonl` for a single `finalize <cid>`.

**State is saved after every send.** `process` records each bottle (its id in `delivered_ids`, the
cursor just past its end record, `ledger_head`) as soon as its send succeeds, before it attempts the
next one, and once more when the batch ends. If the process is killed after a send has completed but
before that save, that one bottle is posted again by the next run, and no other: everything sent
before it is already recorded. So delivery is exactly-once except for a one-bottle window. (2.0.0
saved once, after the whole batch, so a kill part-way through re-posted every bottle that run had
already sent.)

Two known gaps, tracked and not addressed by this release: the two sinks still keep *separate*
cursors and dedup state (ADR-001 item 7 merges them, Phase 2), and `notify_closed_dryrun.py` is
still a separate script rather than a `--dry-run` flag (ADR-001 item 10).

## 4. Failure Behaviour

The observer is a cursor over an append-only ledger, so its dangerous failure is not crashing —
it is **rewinding**. A cursor that silently returns to 0 replays every ledger record that has
ever existed into the log, and duplicated output is harder to notice, and harder to undo, than
no output at all.

This section is about the log sink (`miab_observer.py`). The message sink's fail-closed rules,
which differ in detail, are in §3a.

So the state file is treated as load-bearing:

| Condition | Behaviour |
|---|---|
| `queue_state.json` absent | Genuine fresh start. Cursor begins at 0. |
| `queue_state.json` present but unparseable, not a JSON object, or carrying a `last_processed_line` that is not a non-negative integer | **Exit `1`** with `{"ok": false, ...}` on stderr. The cursor is never rewound and nothing is written to the log. |

Recovery is deliberate and belongs to the operator: inspect the file, repair it to the last known
good `last_processed_line`, or delete it to accept a full replay.

Two related guarantees, unchanged: `peek` never advances the cursor or writes to the log, and
`process` advances the cursor only once the batch has been delivered — or when the sweep produced
nothing to deliver.

## Quick Reference

```
on      → enable automated sweeps and active log file writing
off     → disable log writing (silent mode)
status  → view live cursor count, target log file, and active environment parameters
process → sweep the ledger, append new events to the log file, and advance cursor
peek    → inspect new transaction events on stdout without affecting the cursor or log file
```
