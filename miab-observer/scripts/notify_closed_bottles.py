#!/usr/bin/env python3
"""
notify_closed_bottles — deterministic end-state notifier for the MIAB callback ledger.

Watches the append-only callback ledger (state/callbacks/ledger.jsonl, owned by
claw-callback.py) for events that mean a bottle has reached an END STATE:
`resolve`, `cancel`, or `fail`. For each one, it reconstructs that bottle's full
MIAB history from the ledger (every line whose `id` matches, in order) and posts
it as a single Discord message via `openclaw message send`.

Deliberately NOT an agentTurn / reactive cron hook. Per
docs/specs/miab-messaging-dedup-and-cron-sequencing.md (the incident that
produced the July 2026 double-posting/typo'd-channel bug), any LLM turn put in
the send path is the thing that produces duplicate or mistargeted delivery.
This script is pure stdlib + one subprocess call to a fixed CLI with a fixed
delivery target; run it from a `--command` (non-agent) cron job, never an agentTurn.

Read-only over the ledger: never mutates ledger.jsonl or envelope files. The
only files it writes are its own state file (cursor, toggle, delivered ids and a
fingerprint of the ledger the cursor belongs to).

A missing state file is a first run: the cursor starts at the ledger END and nothing is
posted. A state file that exists but cannot be trusted, or a cursor that no longer fits
the ledger, makes the command exit 1 with {"ok": false, ...} on stderr and change nothing.
`render` reads no state at all. See the "state" section below for the full rules.

Path resolution (mirrors miab_observer.py's conventions):
  - CLAW_HOME              : broker root                 (default: ~/.openclaw)
  - CLAW_LEDGER            : explicit ledger path         (overrides CLAW_HOME/state/callbacks/ledger.jsonl)
  - CLAW_CLOSED_STATE      : explicit state-file path     (overrides CLAW_HOME/state/callbacks/closed_bottle_state.json)
  - CLAW_CLOSED_TARGET     : delivery target for `message send --target` (REQUIRED; no
                             default — commands that can deliver fail closed when it is unset)
  - CLAW_CLOSED_ACCOUNT    : optional --account for `message send`
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

END_EVENTS = {"resolve", "cancel", "fail"}

# --------------------------------------------------------------------------- paths
def claw_home() -> Path:
    return Path(os.environ.get("CLAW_HOME", "~/.openclaw")).expanduser()

def ledger_file() -> Path:
    env = os.environ.get("CLAW_LEDGER")
    if env:
        return Path(env).expanduser()
    return claw_home() / "state" / "callbacks" / "ledger.jsonl"

def state_file() -> Path:
    env = os.environ.get("CLAW_CLOSED_STATE")
    if env:
        return Path(env).expanduser()
    return claw_home() / "state" / "callbacks" / "closed_bottle_state.json"

def target_channel_or_none() -> str | None:
    """The configured delivery target, or None. For introspection only — never
    use this to build a send command."""
    t = os.environ.get("CLAW_CLOSED_TARGET", "").strip()
    return t or None

def target_channel() -> str:
    """The delivery target, or fail closed. There is deliberately no default:
    a hardcoded channel id is both a secret in committed text and a way to
    mistarget delivery on a host that never configured this notifier."""
    t = target_channel_or_none()
    if t is None:
        print(json.dumps({"ok": False,
                          "error": "CLAW_CLOSED_TARGET is unset; refusing to deliver",
                          "next_step": "export CLAW_CLOSED_TARGET=channel:<id> (or the target accepted by `openclaw message send --target`) and re-run"}),
              file=sys.stderr)
        sys.exit(1)
    return t

def account_id() -> str | None:
    return os.environ.get("CLAW_CLOSED_ACCOUNT")

# --------------------------------------------------------------- agent identity map
AGENT_MAP = {
    "main": "✨ LYRA (Main)",
    "planner": "🥷⚔️ SPECTRE (Planner)",
    "coder": "💥 Cinder (Coder)",
    "reviewer": "🥷👁️ ECHO (Reviewer)",
    "debug": "🔬 Zero (Debug)",
    "utility": "🛠️ Swift (Utility)",
    "sigma": "⚡ SIGMA (Portfolio)",
    "free": "🌌 VOID (Scout)",
    "sweep": "🧹 Callback Reaper",
    "system": "⚙️ System",
}

def who(name):
    return AGENT_MAP.get(name, name or "Unknown")

# Model running behind each agent — primary + fallback chain (mirrors
# agents.entries[<id>].model in openclaw.json). Keys are the bare agent ids used in
# ledger 'by'/'to'/'wake' fields.
MODEL_MAP = {
    "main": {"primary": "deepseek-v4-flash", "fallbacks": ["gemini-3-flash-preview", "deepseek-v4-pro", "claude-sonnet-5", "gemini-3.6-flash", "gpt-5.6-terra"]},
    "planner": {"primary": "claude-sonnet-5", "fallbacks": ["gpt-5.6-terra", "gemini-3.6-flash", "deepseek-v4-pro"]},
    "coder": {"primary": "gpt-5.6-terra", "fallbacks": ["claude-sonnet-5", "deepseek-v4-flash", "gemini-3.6-flash"]},
    "reviewer": {"primary": "claude-opus-latest", "fallbacks": ["claude-opus-5", "gemini-3.6-flash", "gpt-5.6-terra", "deepseek-v4-pro"]},
    "debug": {"primary": "gemini-3.6-flash", "fallbacks": ["deepseek-v4-flash", "claude-sonnet-5", "gpt-5.6-terra"]},
    "utility": {"primary": "ling-3.0-flash:free", "fallbacks": ["gemini-3.5-flash-lite", "claude-haiku-latest", "deepseek-v4-flash"]},
    "sigma": {"primary": "claude-sonnet-5", "fallbacks": ["claude-opus-5", "gpt-5.6-terra", "gemini-3.6-flash"]},
    "free": {"primary": "ling-3.0-flash:free", "fallbacks": ["nemotron-3-ultra-550b:free", "laguna-s-2.1:free"]},
    "local": {"primary": "local-qwen3.5-4b", "fallbacks": ["ling-3.0-flash:free"]},
}


def who_model(name, short=True):
    """Compact '<model>' tag for an agent id. short=True -> just primary.
    short=False -> 'primary → fb1, fb2' (full chain). Empty if unknown."""
    info = MODEL_MAP.get(name)
    if not info:
        return ""
    if short:
        return info["primary"]
    fbs = info.get("fallbacks") or []
    if not fbs:
        return info["primary"]
    return f"{info['primary']} → {', '.join(fbs)}"

END_ICON = {"resolve": "✅", "cancel": "❌", "fail": "⚠️"}
END_LABEL = {"resolve": "Resolved", "cancel": "Cancelled", "fail": "Failed/Reaped"}

# --------------------------------------------------------------------------- state
# closed_bottle_state.json is load-bearing. This sink is a cursor over an append-only
# ledger, and its dangerous failure is not crashing but REWINDING: a rewind re-posts every
# closed bottle in the ledger to a chat channel, which is harder to notice than a missing
# post and impossible to unsend. (miab_observer.py fixed the same bug in its log sink in
# 1.3.0; it sat here until 2.0.1.) So:
#
#   * a MISSING state file is the only fresh start, and a fresh start begins at the ledger
#     END: it records where the ledger is and posts nothing. `finalize <cid>` is how you
#     post one older bottle on demand.
#   * a PRESENT but unusable state file exits 1 and is never rewritten.
#   * a cursor beyond the ledger is ambiguous -- truncation, or the broker's rotation (it
#     renames ledger.jsonl and starts a new one). `ledger_head`, the SHA-256 of the first
#     non-empty ledger line, tells the two apart; see reconcile_cursor().
#
# The file is never renamed, writes stay atomic, and `ledger_head` is optional so a 2.0.0
# state file still loads.
LEDGER_HEAD_RE = re.compile(r"[0-9a-f]{64}")


def ledger_head(lines) -> str | None:
    """The ledger's fingerprint: SHA-256 (hex) of its first non-empty line, as
    load_all_lines() returns it, or None for an empty ledger. The ledger is append-only,
    so this holds still while it grows; a rotation starts a new file whose first record
    differs (every record is timestamped)."""
    return hashlib.sha256(lines[0].encode("utf-8")).hexdigest() if lines else None


def _refuse(error: str, refusing: str, remedy: str) -> None:
    """Fail closed: a JSON object with "ok": false on stderr, exit 1. Same shape as
    miab_observer._refuse_unusable_state(). Callers must not have written anything."""
    print(json.dumps({
        "ok": False,
        "error": error,
        "state_file": str(state_file()),
        "refusing": refusing,
        "remedy": remedy,
    }, indent=2), file=sys.stderr)
    sys.exit(1)


def _refuse_unusable_state(reason: str) -> None:
    _refuse(
        f"state file unusable: {reason}",
        "resetting the cursor here would re-post every closed bottle in the ledger to the chat target",
        "inspect the file, then repair it (keep last_processed_line and delivered_ids if you can "
        "still read them), or delete it to start fresh at the ledger end, which posts nothing; "
        "`finalize <cid>` posts any bottle that gap skipped")


def _check_state(state) -> dict:
    """Validate a parsed state file or exit 1. Absent optional keys are fine (a 2.0.0 file
    has no ledger_head); present-but-wrong ones are not, because every default here is a
    silent rewind: no cursor means cursor 0, no delivered_ids means no dedup."""
    if not isinstance(state, dict):
        _refuse_unusable_state(f"expected a JSON object, found {type(state).__name__}")
    if "last_processed_line" not in state:
        _refuse_unusable_state("last_processed_line is missing")
    cursor = state["last_processed_line"]
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
        _refuse_unusable_state(f"last_processed_line must be a non-negative integer, found {cursor!r}")
    if "delivered_ids" in state:
        ids = state["delivered_ids"]
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            _refuse_unusable_state("delivered_ids must be a list of strings")
    if "enabled" in state and not isinstance(state["enabled"], bool):
        _refuse_unusable_state(f"enabled must be true or false, found {state['enabled']!r}")
    if "ledger_head" in state:
        head = state["ledger_head"]
        if not isinstance(head, str) or not LEDGER_HEAD_RE.fullmatch(head):
            _refuse_unusable_state("ledger_head must be a SHA-256 hex digest")
    return state


def read_state() -> dict | None:
    """The state file as written, or None if there is none (a first run). Exits 1 if it is
    present but unusable. Never writes."""
    p = state_file()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:          # ValueError: not UTF-8
        _refuse_unusable_state(f"cannot read it: {e}")
    try:
        state = json.loads(text)
    except (ValueError, RecursionError) as e:
        _refuse_unusable_state(f"not valid JSON: {e}")
    return _check_state(state)


def new_state(lines) -> dict:
    """The one way a state is ever created: enabled, cursor at the CURRENT end of the
    ledger, nothing delivered, plus the ledger's fingerprint (omitted only when there is
    no ledger yet). `process`, `on`, `off` and `finalize` all come through here, so none
    of them can leave behind a cursor-0 state that a later `process` would backfill from."""
    state = {"enabled": True, "last_processed_line": len(lines), "delivered_ids": []}
    head = ledger_head(lines)
    if head is not None:
        state["ledger_head"] = head
    return state


def load_state() -> dict:
    """The existing state (validated), or a fresh one if there is none. For commands that
    go on to write it. Exits 1 if the file is present but unusable."""
    state = read_state()
    return state if state is not None else new_state(load_all_lines())


def save_state(state: dict) -> None:
    p = state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)


def reconcile_cursor(state: dict, lines) -> tuple[int, str, str | None] | None:
    """Decide where this scan starts. The only place the cursor is compared with the ledger;
    `process` and `collect_new()` (so `peek`) both call it.

    Returns (start, head, note): the line to scan from, the ledger's current fingerprint
    (to be recorded), and an operator-facing note (or None). Returns None when there is no
    ledger or it is empty -- nothing to scan, and the caller must leave the state alone.
    Exits 1 (writing nothing) when the cursor cannot be trusted:

      stored ledger_head | situation             | action
      -------------------+-----------------------+--------------------------------------
      equals current     | cursor <= length      | normal
      equals current     | cursor >  length      | truncation: exit 1
      differs            | any cursor            | new ledger: start at 0, record the new
                         |                       | head, delivered_ids dedups
      absent (2.0.0)     | cursor <= length      | adopt the current head, continue
      absent (2.0.0)     | cursor >  length      | ambiguous: exit 1 with a remedy
      any                | ledger missing/empty  | no-op
    """
    total = len(lines)
    if total == 0:
        return None
    head = ledger_head(lines)
    cursor = state["last_processed_line"]
    stored = state.get("ledger_head")

    if stored == head:
        if cursor > total:
            _refuse(
                f"ledger looks truncated: the cursor is at line {cursor} but the ledger has "
                f"{total} line(s), and its first line is the one this state was recorded against",
                "rewinding to line 0 would re-post every closed bottle in the ledger",
                "if the shorter ledger is the one you want, set last_processed_line in the state "
                "file to at most the ledger's line count, or delete the state file to restart at "
                "the ledger end (posts nothing); otherwise restore the ledger")
        return cursor, head, None

    if stored is None:
        if cursor > total:
            _refuse(
                "ambiguous cursor, cannot tell truncation from rotation: the cursor is at line "
                f"{cursor} but the ledger has {total} line(s), and this state file has no "
                "ledger_head to compare (it was written before 2.0.1)",
                "guessing wrong either re-posts closed bottles or silently skips new ones",
                "if the broker rotated the ledger, set last_processed_line to 0 (delivered_ids "
                "still stops recorded bottles being re-posted); if it was truncated, set it to "
                "the ledger's line count; or delete the state file to restart at the ledger end "
                "(posts nothing)")
        return cursor, head, None

    return 0, head, ("New ledger detected (its first line differs from the one recorded, so it "
                     "was replaced or rotated): scanning from line 0, with delivered_ids "
                     "preventing re-posts.")


# ----------------------------------------------------------------- summarization
def sanitize(text, limit=500):
    if not text:
        return ""
    lines = [l.strip() for l in str(text).split("\n") if l.strip()]
    cleaned = " ".join(" ".join(lines).split())
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned

# ----------------------------------------------------------------- history render
def render_step(rec):
    """One ledger record for a bottle -> one short history line."""
    event = rec.get("event")
    by = who(rec.get("by"))
    bym = who_model(rec.get("by"))
    tag = f" [{bym}]" if bym else ""
    if event == "create":
        to = who(rec.get("to"))
        tom = who_model(rec.get("to"))
        totag = f" [{tom}]" if tom else ""
        return f"📥 created by {by}{tag} -> {to}{totag}"
    if event == "forward":
        to = who(rec.get("to"))
        tom = who_model(rec.get("to"))
        totag = f" [{tom}]" if tom else ""
        return f"➡️ forwarded by {by}{tag} -> {to}{totag}"
    if event == "return":
        return f"↩️ returned by {by}{tag}, waking {who(rec.get('wake'))}"
    if event == "resolve":
        return f"✅ resolved by {by}{tag}"
    if event == "cancel":
        return f"❌ cancelled by {by}{tag}" + (f" ({rec.get('reason')})" if rec.get("reason") else "")
    if event == "fail":
        return f"⚠️ failed/reaped by {by}{tag}" + (f" ({rec.get('reason')})" if rec.get("reason") else "")
    if event == "corrupt":
        return f"🗑️ quarantined ({rec.get('reason', 'corrupt envelope')})"
    return f"{event} by {by}{tag}"

def load_all_lines():
    lf = ledger_file()
    if not lf.exists():
        return []
    with lf.open("r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def _parse_records(lines) -> list:
    """Every ledger line as a dict. A line that is not valid JSON, or not a JSON object,
    becomes {} so that list indexes keep lining up with the cursor."""
    out = []
    for l in lines:
        try:
            rec = json.loads(l)
        except (ValueError, RecursionError):
            rec = None
        out.append(rec if isinstance(rec, dict) else {})
    return out


def end_bottle_id(rec: dict) -> str | None:
    """The bottle id if `rec` is an end-state record (resolve/cancel/fail) with a usable
    id, else None. The type checks are not pedantry: ledger fields are untrusted, an
    unhashable `event` would crash the sweep part-way through a batch (re-posting that
    batch's earlier sends on the next run), and a non-string id recorded in delivered_ids
    would make the state file unusable on the next load."""
    event, cid = rec.get("event"), rec.get("id")
    if isinstance(event, str) and event in END_EVENTS and isinstance(cid, str) and cid:
        return cid
    return None

def format_closed_bottle(cid: str, all_records: list, end_rec: dict) -> str:
    """Build the full-history report message for one just-closed bottle."""
    bottle_records = [r for r in all_records if r.get("id") == cid]
    create_rec = next((r for r in bottle_records if r.get("event") == "create"), None)
    task = sanitize(end_rec.get("task") or (create_rec or {}).get("task", ""), limit=300)
    end_event = end_rec.get("event")
    icon = END_ICON.get(end_event, "🔔")
    label = END_LABEL.get(end_event, end_event)

    lines = [f"{icon} [MIAB Bottle {label}] {cid}"]
    if task:
        lines.append(f"   Task: {task}")
    if end_event == "resolve" and end_rec.get("result"):
        lines.append(f"   Result: {sanitize(end_rec.get('result'), limit=400)}")
    if end_event == "cancel" and end_rec.get("reason"):
        lines.append(f"   Reason: {end_rec.get('reason')}")
    if end_event == "fail" and end_rec.get("reason"):
        lines.append(f"   Reason: {end_rec.get('reason')}")
    lines.append(f"   Hops: {len(bottle_records)}")
    lines.append("   History:")
    for r in bottle_records:
        lines.append(f"     - {render_step(r)}")
    return "\n".join(lines)

# ----------------------------------------------------------------- collection
def find_end_record(cid: str) -> dict | None:
    """Locate the ledger's end-state record (resolve/cancel/fail) for one bottle."""
    for rec in _parse_records(load_all_lines()):
        if end_bottle_id(rec) == cid:
            return rec
    return None


def render_bottle(cid: str) -> tuple[str | None, str]:
    """Deterministic output for ONE closed bottle. Returns (message, status)."""
    end_rec = find_end_record(cid)
    if end_rec is None:
        return None, f"No end-state (resolve/cancel/fail) event found for bottle {cid}."
    all_records = _parse_records(load_all_lines())
    return format_closed_bottle(cid, all_records, end_rec), f"Rendered bottle {cid}."


def is_delivered(cid: str) -> bool:
    return cid in load_state().get("delivered_ids", [])


DELIVERED_IDS_CAP = 500


def _remember_delivered(state: dict, cid: str) -> None:
    """Record `cid` as delivered in an in-memory state dict, bounded.

    Callers that also mutate the cursor MUST use this and save once, rather than
    mark_delivered() — that re-reads state from disk and would drop their cursor.
    """
    ids = state.setdefault("delivered_ids", [])
    if cid not in ids:
        ids.append(cid)
    if len(ids) > DELIVERED_IDS_CAP:
        del ids[:-DELIVERED_IDS_CAP]


def mark_delivered(cid: str) -> None:
    state = load_state()
    _remember_delivered(state, cid)
    save_state(state)


def collect_new(state, advance):
    """Scan the ledger from the cursor for new end-state events; for each,
    render the full-history message using ALL records for that bottle id
    (not just the ones after the cursor). Returns (messages, status, new_cursor).

    Like `process`, it asks reconcile_cursor() where to start (so `peek` refuses a
    truncated ledger exactly as `process` does) and leaves out bottles already in
    delivered_ids, so what it shows is what `process` would send. It never writes."""
    lines = load_all_lines()
    total = len(lines)
    plan = reconcile_cursor(state, lines)
    if plan is None:
        return [], "Ledger missing or empty: nothing to scan.", state["last_processed_line"]
    cursor, _head, note = plan
    suffix = f" {note}" if note else ""
    if cursor >= total:
        return [], "No new callback events." + suffix, total

    all_records = _parse_records(lines)
    seen = set(state.get("delivered_ids", []))
    messages = []
    for rec in all_records[cursor:]:
        cid = end_bottle_id(rec)
        if cid is not None and cid not in seen:
            seen.add(cid)
            messages.append(format_closed_bottle(cid, all_records, rec))

    new_cursor = total if advance else cursor
    status = (f"Scanned {total - cursor} new ledger line(s), found {len(messages)} closed "
              f"bottle(s)." + suffix)
    return messages, status, new_cursor


# ----------------------------------------------------------------- delivery
def deliver_one(message: str) -> bool:
    """Deterministic delivery: shell out to `openclaw message send`. No LLM
    in this path. Returns True on success."""
    cmd = ["openclaw", "message", "send", "--channel", "discord",
           "--target", target_channel(), "--message", message]
    acct = account_id()
    if acct:
        cmd += ["--account", acct]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"delivery failed (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"delivery failed: {e}", file=sys.stderr)
        return False

# --------------------------------------------------------------------------- main
def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def first_run_note(total: int) -> str:
    return (f"First run: no state file, so the cursor starts at the ledger end (line {total}) "
            "and nothing is posted. Bottles that close from now on are delivered; "
            "`finalize <cid>` posts an older one on demand.")


def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "process"

    if cmd == "on":
        target = target_channel()       # fail closed before anything is written
        state = load_state()
        state["enabled"] = True
        save_state(state)
        print(json.dumps({"enabled": True, "status": "ON", "target": target}))
        return

    if cmd == "off":
        state = load_state()
        state["enabled"] = False
        save_state(state)
        print(json.dumps({"enabled": False, "status": "OFF"}))
        return

    if cmd == "status":
        state = read_state()
        lines = load_all_lines()
        out = {
            "enabled": True if state is None else state.get("enabled", True),
            "status": "ON" if state is None or state.get("enabled", True) else "OFF",
            "state_present": state is not None,
            "last_processed_line": len(lines) if state is None else state["last_processed_line"],
            "ledger_lines": len(lines),
            "ledger_head": None if state is None else state.get("ledger_head"),
            "ledger": str(ledger_file()),
            "state_file": str(state_file()),
            "target": target_channel_or_none(),
        }
        if state is None:
            out["note"] = first_run_note(len(lines))
        print(json.dumps(out, indent=2))
        return

    if cmd == "peek":
        state = read_state()
        if state is None:
            _emit({"messages": [], "status": first_run_note(len(load_all_lines())),
                   "delivered": False})
            return
        messages, status, _ = collect_new(state, advance=False)
        _emit({"messages": messages, "status": status, "delivered": False})
        return

    if cmd == "render":
        """py script.py render <cid>  ->  print the deterministic message (no send)."""
        if len(sys.argv) < 3:
            print(json.dumps({"ok": False, "error": "render requires a bottle id: render <cid>"}), file=sys.stderr)
            sys.exit(2)
        cid = sys.argv[2]
        msg, status = render_bottle(cid)
        if msg is None:
            print(json.dumps({"ok": False, "error": status}), file=sys.stderr)
            sys.exit(1)
        print(msg)
        return

    if cmd == "finalize":
        """py script.py finalize <cid>  ->  render + deliver the message once (exactly-once)."""
        if len(sys.argv) < 3:
            print(json.dumps({"ok": False, "error": "finalize requires a bottle id: finalize <cid>"}), file=sys.stderr)
            sys.exit(2)
        cid = sys.argv[2]
        if is_delivered(cid):       # also the fail-closed check on an unusable state file
            print(json.dumps({"ok": True, "delivered": False,
                              "status": f"Bottle {cid} already finalized — skipping (exactly-once)."}, indent=2))
            return
        msg, status = render_bottle(cid)
        if msg is None:
            print(json.dumps({"ok": False, "error": status}), file=sys.stderr)
            sys.exit(1)
        if deliver_one(msg):
            mark_delivered(cid)
            print(json.dumps({"ok": True, "delivered": True,
                              "status": f"Finalized bottle {cid} and posted to {target_channel()}."},
                             indent=2))
        else:
            print(json.dumps({"ok": False, "delivered": False,
                              "error": f"Delivery failed for bottle {cid}; cursor not advanced (will retry)."},
                             indent=2), file=sys.stderr)
            sys.exit(1)
        return

    if cmd == "process":
        state = read_state()            # exits 1 if present but unusable
        lines = load_all_lines()
        total = len(lines)

        if state is None:               # the only fresh start: record the ledger end, post nothing
            if total == 0:
                _emit({"messages": [], "delivered": True,
                       "status": "Ledger missing or empty: nothing to scan, and no state file was created."})
                return
            save_state(new_state(lines))
            _emit({"messages": [], "delivered": True, "status": first_run_note(total)})
            return

        if not state.get("enabled", True):
            print(json.dumps({"messages": [], "status": "Notifier DISABLED — skipping sweep.", "delivered": False}))
            return

        plan = reconcile_cursor(state, lines)       # exits 1 on truncation / ambiguity
        if plan is None:
            _emit({"messages": [], "delivered": True,
                   "status": "Ledger missing or empty: nothing to scan; state left untouched."})
            return
        cursor, head, note = plan
        suffix = f" {note}" if note else ""

        if cursor >= total:
            if state.get("ledger_head") != head:        # learn the fingerprint of a 2.0.0 state
                state["ledger_head"] = head
                save_state(state)
            _emit({"messages": [], "status": "No new callback events." + suffix, "delivered": True})
            return

        all_records = _parse_records(lines)
        delivered_msgs = []
        skipped = []
        # Deliver in order; stop advancing the cursor at the first delivery
        # failure so nothing is skipped on the next run (at-least-once,
        # exactly-once in the common case).
        #
        # The cursor alone is NOT a dedup guard. `finalize` (the claw-callback
        # hook) records ids in delivered_ids without moving the cursor, so any
        # bottle it announced still sits in this scan window. Consult
        # delivered_ids per bottle — that is the only guard both paths share.
        new_cursor = total
        for i, rec in enumerate(all_records[cursor:], start=cursor):
            cid = end_bottle_id(rec)
            if cid is None:
                continue
            if cid in state.get("delivered_ids", []):
                skipped.append(cid)
                continue
            msg = format_closed_bottle(cid, all_records, rec)
            if deliver_one(msg):
                delivered_msgs.append(msg)
                _remember_delivered(state, cid)
            else:
                new_cursor = i
                break

        state["last_processed_line"] = new_cursor
        state["ledger_head"] = head
        save_state(state)
        status = (f"Delivered {len(delivered_msgs)} closed-bottle report(s); "
                  f"cursor now {new_cursor}/{total}.")
        if skipped:
            status += f" Skipped {len(skipped)} already-delivered: {', '.join(skipped)}."
        status += suffix
        print(json.dumps({
            "messages": delivered_msgs,
            "skipped_already_delivered": skipped,
            "status": status,
            "delivered": True,
        }, indent=2))
        return

    print(json.dumps({"ok": False, "error": f"unknown command: {cmd}",
                      "commands": ["on", "off", "status", "process", "peek", "render", "finalize"]}), file=sys.stderr)
    sys.exit(2)

if __name__ == "__main__":
    main()
