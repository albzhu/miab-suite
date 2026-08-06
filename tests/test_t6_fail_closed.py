"""
T6 — fail closed everywhere. [S7]

Three separate silent-failure paths, now closed:
  1. Malformed JSON input (--resume-json) used to raise a raw traceback.
  2. Corrupt envelopes on disk used to raise a raw traceback out of load().
  3. `wake` on a registry miss emitted {"ok": false, ...} but exited 0 — no
     wrapper or scheduler could detect the failure.
  4. `list`/`sweep` swallowed every exception with a bare `except: continue`,
     silently hiding corrupt envelopes forever (an "immortal zombie").
"""
from conftest import parse_json


def test_malformed_resume_json_exits_nonzero_no_traceback(run_cb):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--resume-json", "not-json")
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    err = parse_json(r.stderr)
    assert err["ok"] is False


def test_corrupt_envelope_on_disk_exits_nonzero_no_traceback(run_cb, claw_home):
    cb_dir = claw_home / "state" / "callbacks"
    cb_dir.mkdir(parents=True, exist_ok=True)
    bad = cb_dir / "cb-20260101000000-abcdef.json"
    bad.write_text("not valid json{{{")

    r = run_cb("show", "--id", "cb-20260101000000-abcdef")
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    err = parse_json(r.stderr)
    assert err["ok"] is False


def test_wake_registry_miss_exits_nonzero(run_cb):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "unregistered_agent", "--summary", "s")
    cid = parse_json(r.stdout)["id"]

    r2 = run_cb("wake", "--id", cid)
    out = parse_json(r2.stdout)
    assert out["ok"] is False
    assert out["registry_miss"] is True
    assert r2.returncode != 0, "ok:false must never exit 0 — a scheduler needs to detect this"


def test_list_quarantines_corrupt_envelope_instead_of_hiding_it(run_cb, claw_home):
    cb_dir = claw_home / "state" / "callbacks"
    cb_dir.mkdir(parents=True, exist_ok=True)
    bad = cb_dir / "cb-20260101000000-abcdef.json"
    bad.write_text("not valid json{{{")

    r = run_cb("list", "--json")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["quarantined"] == 1
    assert not bad.exists(), "corrupt envelope must be moved out of the hot dir"
    assert (cb_dir / "archive" / "corrupt" / bad.name).exists()


def test_sweep_quarantines_corrupt_envelope_instead_of_hiding_it(run_cb, claw_home):
    cb_dir = claw_home / "state" / "callbacks"
    cb_dir.mkdir(parents=True, exist_ok=True)
    bad = cb_dir / "cb-20260101000000-abcdef.json"
    bad.write_text("not valid json{{{")

    r = run_cb("sweep", "--older-than", "0")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["quarantined"] == 1
    assert (cb_dir / "archive" / "corrupt" / bad.name).exists()


def test_sweep_quarantines_id_mismatched_envelope(run_cb, claw_home):
    """An envelope whose internal id doesn't match its filename (tampering, or
    a legacy file) must not crash the sweep loop via envelope_path()'s strict
    validate_id() — it should be quarantined like any other bad envelope."""
    import json as _json

    cb_dir = claw_home / "state" / "callbacks"
    cb_dir.mkdir(parents=True, exist_ok=True)
    fname = "cb-20260101000000-abcdef.json"
    (cb_dir / fname).write_text(_json.dumps({
        "id": "cb-99999999999999-999999",  # mismatched on purpose
        "status": "pending",
        "updatedAt": "2020-01-01T00:00:00Z",
        "history": [],
    }))

    r = run_cb("sweep", "--older-than", "0", "--fail")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["quarantined"] == 1
    assert out["stale_count"] == 0
