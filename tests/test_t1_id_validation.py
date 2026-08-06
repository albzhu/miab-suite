"""
T1 — validate --id, confine all resolved paths to the state root. [S0]

Regression guard for the arbitrary-file read/write/delete primitive: a
caller-supplied id like `../../victim` used to interpolate straight into a
path with no validation, so `show`/`return`/`resolve` could read, overwrite,
or unlink any .json file the process could reach.
"""
import json

from conftest import parse_json


TRAVERSAL_IDS = [
    "../../victim",
    "../../../etc/passwd",
    "cb-20260101000000-abcdef/../../../victim",
    "/etc/passwd",
    "cb-1-abcdef",              # wrong digit count
    "cb-20260101000000-ABCDEF",  # uppercase hex not allowed
    "cb-20260101000000-abcdef-extra",
    "",
]


def test_show_rejects_traversal_ids(run_cb):
    for bad_id in TRAVERSAL_IDS:
        r = run_cb("show", "--id", bad_id)
        assert r.returncode != 0, f"id {bad_id!r} should have been rejected"
        err = parse_json(r.stderr)
        assert err["ok"] is False
        assert "Traceback" not in r.stderr


def test_return_rejects_traversal_ids(run_cb):
    for bad_id in TRAVERSAL_IDS:
        r = run_cb("return", "--id", bad_id, "--from", "evil", "--result", "x")
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


def test_resolve_does_not_delete_file_outside_state_root(run_cb, tmp_path):
    victim = tmp_path / "victim.json"
    victim.write_text(json.dumps({"secret": "data"}))

    # Traversal id crafted to land on the victim file relative to cb_dir().
    traversal_id = "../" * 8 + str(victim).lstrip("/")
    r = run_cb("resolve", "--id", traversal_id, "--from", "evil")

    assert r.returncode != 0
    assert victim.exists(), "resolve must not have deleted a file outside the state root"
    assert json.loads(victim.read_text()) == {"secret": "data"}


def test_valid_format_nonexistent_id_fails_cleanly(run_cb):
    r = run_cb("show", "--id", "cb-99999999999999-aaaaaa")
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    err = parse_json(r.stderr)
    assert err["ok"] is False


def test_generated_ids_pass_validation(run_cb):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--summary", "s")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    assert out["ok"] is True
    cid = out["id"]

    r2 = run_cb("show", "--id", cid, "--json")
    assert r2.returncode == 0
    assert parse_json(r2.stdout)["id"] == cid


def test_cancel_archive_path_is_confined(run_cb, claw_home):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--summary", "s")
    cid = parse_json(r.stdout)["id"]

    r2 = run_cb("cancel", "--id", cid, "--from", "a", "--reason", "test")
    assert r2.returncode == 0
    out = parse_json(r2.stdout)
    archived_to = out["archived_to"]
    assert archived_to is not None
    # Archived file must live under claw_home, never outside it.
    assert str(claw_home) in archived_to
    assert (claw_home / "state" / "callbacks" / "archive" / f"{cid}.json").exists()
