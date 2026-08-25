---
name: "interagent-queue"
description: "Monitor and log MIAB transaction ledger events to a file. Requires miab-broker as a prerequisite."
permissions:
  env: [CLAW_HOME, LYRA_WORKSPACE, CLAW_QUEUE_LOG]
  file_read:
    - "$CLAW_HOME/state/callbacks/ledger.jsonl"
    - "$CLAW_HOME/state/callbacks/agent-registry.json"
  file_write:
    - "$LYRA_WORKSPACE/state/callbacks/queue_state.json"
    - "$CLAW_HOME/logs/interagent-queue.log"
  network: []
---

# Interagent Queue — Asynchronous Transaction Observer

This skill governs the transaction processing, formatting, and file-based logging for the **Message-in-a-Bottle (MIAB) LIFO Callback Stack**. It decouples the observer and human-readability layers from the core `miab-broker` protocol.

---

## Prerequisites

- **`miab-broker` skill**: `interagent-queue` operates strictly as an observer layer over `miab-broker`. `miab-broker` must be installed and initialized to produce the transaction ledger (`$CLAW_HOME/state/callbacks/ledger.jsonl`).

---

## 1. What the Interagent Queue Observer Does

The observer (`scripts/interagent_queue.py`) is a transaction monitor that tails the append-only callback events log (`state/callbacks/ledger.jsonl`). It parses events in real-time or via frequent interval sweeps, matches logical agent references (like `main`, `planner`, `coder`, or `reviewer`) with friendly icons, and formats them into clean, compact, human-readable log entries.

Transaction events are written directly to the interagent queue log file (`$CLAW_HOME/logs/interagent-queue.log` by default, configurable via `CLAW_QUEUE_LOG`).

---

## 2. Invocations & Commands

The utility script `interagent_queue.py` can be driven from the CLI to enable/disable sweeps, check cursor tracking status, or run isolated manual analysis.

Invoke it at `scripts/interagent_queue.py`, resolved against wherever this skill is installed for you (written `<interagent-queue>` below). There is no fixed absolute path that is correct across installs.

```bash
# Toggle logging sweeps
python3 <interagent-queue>/scripts/interagent_queue.py on
python3 <interagent-queue>/scripts/interagent_queue.py off

# Check cursor status, live state file, log file path, and target ledger
python3 <interagent-queue>/scripts/interagent_queue.py status

# Manually process and sweep all un-processed ledger records into the log file
python3 <interagent-queue>/scripts/interagent_queue.py process

# Peek at new ledger records inside stdout WITHOUT updating your cursor or writing to the log file
python3 <interagent-queue>/scripts/interagent_queue.py peek
```

---

## 3. Storage & State Management

To decouple concerns and ensure multi-platform flexibility (e.g. running under separate user accounts, home directories, or containers), all operational locations resolve dynamically relative to home environments — nothing is hardcoded to a host path:

- **State Document:** `$LYRA_WORKSPACE/state/callbacks/queue_state.json` tracks cursor indexing (`last_processed_line`) and live enabled status.
- **Active Ledger Source:** `$CLAW_HOME/state/callbacks/ledger.jsonl` (provided by `miab-broker`).
- **Target Log File:** `$CLAW_HOME/logs/interagent-queue.log` (overrideable via `CLAW_QUEUE_LOG`).

---

## Quick Reference

```
on      → enable automated sweeps and active log file writing
off     → disable log writing (silent mode)
status  → view live cursor count, target log file, and active environment parameters
process → sweep the ledger, append new events to the log file, and advance cursor
peek    → inspect new transaction events on stdout without affecting the cursor or log file
```
