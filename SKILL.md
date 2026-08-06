---
name: miab-broker
description: Operate the Message-in-a-Bottle (MIAB) LIFO callback stack — the async inter-agent transport that lets agents delegate work, yield their turn, and get woken when results return instead of CPU-idling on poll loops. Use when registering wake paths, creating/forwarding/returning/resolving callbacks, or invoking the callback reaper.
---

# MIAB Broker — Asynchronous Callback Message-in-a-Bottle Stack

This skill formalizes the **Message-in-a-Bottle (MIAB) LIFO Callback Stack**: the file-based asynchronous transport that the LYRA agent network uses to hand work between specialist agents without blocking a runtime turn.

It governs the protocol lifecycle of a bottle as it travels down a delegation chain and unwinds back up (`register → create → forward → return → resolve`).

---

## 1. What the MIAB LIFO Callback Stack Is

Traditional multi-agent coordination wastes turns. A caller delegates a task, then **sits in a poll loop** asking "are you done yet?" — burning CPU, wall-clock, and tokens while the holder does the real work. The MIAB stack removes the poll loop entirely.

Instead of waiting, a caller pushes a lightweight **resume frame** onto an active registry ledger and **ends its turn immediately**. The frame is the "message in a bottle": a compact, self-contained capsule describing *what to do when woken* — a one-line `summary`, an ordered set of `steps`, what the caller `expects` back, and how to `integrate` the result. The agent's expensive session is freed the instant the bottle is dispatched.

The structure is a **stack (LIFO)**, not a flat queue. When a holder delegates further mid-chain (a `forward`), its own resume frame is **pushed on top** of the parent's frame, and the whole stack of frames travels with the work. As each agent finishes its part and calls `return`, the top frame is popped and its `wake` target is resurfaced — execution unwinds back up the chain in reverse order, exactly like a function call stack. The agent at the bottom of the stack is the **terminal root** (the original caller); when control returns to it, it finishes the overall task and `resolve`s the bottle.

```
       [Caller / Root: LYRA]            ← terminal root (bottom of stack)
             │  create: push resume frame, dispatch callback://<id>, END TURN
             ▼
      [Holder: SPECTRE]                 ← frame pushed on forward
             │  plans; forward: push its own frame on top, dispatch onward, END TURN
             ▼
       [Holder: Cinder]                 ← top of stack
             │  does the work; return: pop frame, wake SPECTRE
             ▼
      [SPECTRE woken] → return → [LYRA woken] → resolve (bottle deleted, summary kept)
```

---

## 2. Callback Lifecycle (the `claw-callback.py` CLI)

The registry CLI is the single source of truth. **Every command prints a `next_step`** telling the agent exactly what to do next — follow it. There is no single canonical absolute path for this script on every host — each install's skill root differs. Resolve `scripts/bin/claw-callback.py` relative to wherever this skill is installed for you and use that absolute path for every command below (shown as `<miab-broker>`); every `next_step` the CLI prints back is already an absolute, copy-pasteable path regardless of your working directory, so only your very first invocation requires you to supply the path yourself:

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py <cmd> [flags]
```

Full protocol spec lives at `~/.openclaw/CALLBACKS.md`. Always pass `callback://<id>` along when dispatching a task over the agent-to-agent message tool — the bottle ID is the only handle a peer needs.

### a) Register a waking agent

Registers an agent's wake path so the cron wake mechanism knows how to resurface it. Do this once per agent before it can be a callback target.

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py register --agent <name> --agent-id <id>
```

`--agent` is the network nicename (`main`, `planner`, `coder`, …); `--agent-id` is the routable handle the gateway uses to deliver the wake event.

### b) Enqueue / create a MIAB (first hop)

The caller creates a bottle, packages its resume context, dispatches, and ends its turn.

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py create \
  --task "Analyze the generated architecture files" \
  --from main --to planner \
  --summary "Awaiting SPECTRE's architecture spec to integrate into the build plan" \
  --step "Read the emitted architecture map" \
  --step "Diff it against the current module layout" \
  --expects "Clean JSON spec mapping target modules" \
  --integrate "Merge the spec into build-plan.md, then dispatch to coder"
```

After `create`, dispatch the task (including `callback://<id>`) to `--to` via the agent-to-agent message tool, then **END YOUR TURN**.

### c) Forward a mid-chain request

When a holder needs to delegate further, `forward` stacks its own return frame **on top of the parent's** — the entire stack travels with the work.

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py forward \
  --id cb-XXXX --from planner --to coder \
  --summary "Awaiting Cinder's implementation diff to fold back into the plan" \
  --step "Review the patch for spec compliance" \
  --expects "Unified diff + test results"
```

Same resume-context flags as `create`. After forwarding, dispatch onward and end your turn. The parent's frame is untouched underneath; it will be woken after yours pops.

### d) Complete and return up the stack

When an agent finishes its part, it pops its frame and surfaces the next holder up the chain.

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py return \
  --id cb-XXXX --from coder --result "Implemented; 14/14 tests pass, diff attached"
```

`return` prints a ready-to-send `dispatch_message` aimed at the frame's `wake` agent — send it via agent-to-agent and end your turn. If `return` reports `terminal: true`, control has reached the origin (bottom of stack); finish the overall task and proceed to `resolve`.

### e) Resolve the terminal root

The origin agent, once the whole task is delivered to the user, tears the bottle down.

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py resolve --id cb-XXXX --from main
```

The envelope is deleted; a single summary line is retained in the ledger for audit. Only the root (`terminal: true`) should resolve.

### f) Cancel and Abort an Active Stack (Short-Circuit / Abort)

Manually or automatedly cancel a pending task stack to stop runaway processing or token wastage.

```bash
python3 <miab-broker>/scripts/bin/claw-callback.py cancel --id cb-XXXX --from main --reason "Runaway token usage"
```

The callback's status changes to `"cancelled"`. To ensure safety and enable retroactive post-evaluation analysis of what went wrong, the JSON envelope is atomically moved out of the hot loop into:
📂 `~/.openclaw/state/callbacks/archive/<id>.json`

Any active, stuck sub-agents attempting to load context via `show` or submit results via `return` will immediately fail-fast once the file is moved out of active memory.

### g) List Active Tasks / Callbacks

List all active task hand-offs traveling across our ensemble:

```bash
# Print a clean status table mapping ID, STATUS, HOLDER, STACK, and description
python3 <miab-broker>/scripts/bin/claw-callback.py list

# Print programmatic JSON list representation
python3 <miab-broker>/scripts/bin/claw-callback.py list --json
```

---

## 3. State & Tracking Files

All broker state lives under `$CLAW_HOME/state/callbacks/` — `CLAW_HOME` defaults to `~/.openclaw`. Three artifacts live there:

| file                  | written by        | purpose                                              |
|-----------------------|-------------------|------------------------------------------------------|
| `ledger.jsonl`        | `claw-callback.py`| append-only event log (the audit spine)              |
| `cb-<id>.json`        | `claw-callback.py`| one live envelope per in-flight bottle (the stack)   |
| `agent-registry.json` | `register`        | logical agent → routable `agentId` wake map          |

Envelopes are **deleted on completion** (`resolve`/reaped) — only the one-line ledger summary persists. Documentation uses the logical `state/callbacks/...` path; the observer honors `$CLAW_HOME` so the skill stays portable.

---

## 4. Reaping Stale Bottles (`scripts/reap-callbacks.sh`)

Orphaned bottles (a holder crashed, a wake never fired) would otherwise linger as `pending` forever. The reaper is a thin wrapper over the CLI's deterministic, LLM-free `sweep` subcommand: it marks `pending` envelopes older than a configurable age as `failed`, appends a `fail` ledger event for each, purges the dead envelope, and sweeps any dangling `*.json.tmp` write-handles left by interrupted atomic saves.

```bash
scripts/reap-callbacks.sh                 # default: reap bottles older than 120m (CALLBACK_TTL_MIN)
scripts/reap-callbacks.sh --max-age 6h    # custom threshold (s/m/h/d suffixes)
scripts/reap-callbacks.sh --dry-run       # report what WOULD be reaped, change nothing
```

Under the hood it calls `claw-callback.py sweep --older-than <minutes> --fail` (dry-run drops `--fail`), logs a compact line to `$CLAW_HOME/logs/callback-reaper.log`, and exits non-zero on error so a scheduler can alert. Run it on a periodic cron / launchd agent (hourly or daily) as the network's garbage collector.

---

## Quick Reference

```
register  → enable an agent's wake path (once per agent)
create    → push first resume frame, dispatch, END TURN          (caller)
forward   → stack frame on top, delegate onward, END TURN        (mid-chain holder)
return    → pop frame, wake next holder up the stack             (finished holder)
resolve   → tear down bottle at the origin                       (terminal root)
reap      → fail + clean stale/orphaned bottles                  (garbage collector)
```
