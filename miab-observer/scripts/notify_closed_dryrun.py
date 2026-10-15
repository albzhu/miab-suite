#!/usr/bin/env python3
"""notify_closed_dryrun — sample the deterministic notifier OUTPUT without sending.

Renders the closure message for every finished (resolve/cancel/fail) bottle in the
ledger, exactly as the real notifier would post it, and prints them to stdout so you
can review the format/result before anything goes to Discord. It imports the notifier
module that sits beside it and calls the very functions the notifier calls, so what it
prints is the neutralised, length-capped text -- mentions defused, one message at most
1900 characters -- and not an approximation of it. It reads no state file and never runs
`openclaw`.

Usage:
  python3 notify_closed_dryrun.py                  # all finished bottles
  python3 notify_closed_dryrun.py <cid>            # just one bottle
  python3 notify_closed_dryrun.py --json           # machine-readable list
"""
import json
import sys

# An ordinary import of the sibling module: Python puts this script's own directory first
# on sys.path, so no path juggling or dynamic loading is needed.
import notify_closed_bottles as nb


def all_finished():
    seen = set()
    out = []
    for rec in nb.parse_records(nb.load_all_lines()):
        cid = nb.end_bottle_id(rec)
        if cid is not None and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out

def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv[1:]
    ids = argv[:1] or all_finished()
    results = []
    for cid in ids:
        msg, status = nb.render_bottle(cid)
        results.append({"id": cid, "message": msg, "status": status})
    if as_json:
        print(json.dumps({"count": len(results), "bottles": results}, indent=2))
        return
    for r in results:
        print("=" * 60)
        print(f"Bottle: {nb.sanitize(r['id'], limit=nb.NAME_LIMIT)}")
        print("=" * 60)
        if r["message"]:
            print(r["message"])
        else:
            print(f"  (no message) {r['status']}")
        print()
    print(f"[dry-run] {len(results)} finished bottle(s) rendered. Nothing sent.")

if __name__ == "__main__":
    main()
