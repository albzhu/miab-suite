"""
T7 — constrain and schema-validate resume inputs. [S3]

`--resume-file` used to read any JSON on disk with no containment, and that
content lands verbatim in the dispatch_message sent to another agent — a
file-to-agent exfiltration path. Now confined to $CLAW_HOME unless
--allow-outside, capped at 64KB, and schema-validated with unknown keys
rejected.
"""
import json

from conftest import parse_json


def test_resume_file_outside_claw_home_refused_by_default(run_cb, tmp_path):
    outside = tmp_path / "outside_resume.json"
    outside.write_text(json.dumps({"summary": "exfil attempt"}))

    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--resume-file", str(outside))
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert "outside CLAW_HOME" in err["error"]


def test_resume_file_outside_claw_home_permitted_with_allow_outside(run_cb, tmp_path):
    outside = tmp_path / "outside_resume.json"
    outside.write_text(json.dumps({"summary": "explicitly allowed"}))

    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b",
               "--resume-file", str(outside), "--allow-outside")
    assert r.returncode == 0
    assert parse_json(r.stdout)["ok"] is True


def test_resume_file_inside_claw_home_permitted(run_cb, claw_home):
    inside = claw_home / "resume.json"
    inside.write_text(json.dumps({"summary": "ok", "steps": ["a", "b"]}))

    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--resume-file", str(inside))
    assert r.returncode == 0


def test_oversized_resume_file_refused(run_cb, claw_home):
    big = claw_home / "big.json"
    big.write_text(json.dumps({"summary": "x" * 70_000}))

    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--resume-file", str(big))
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert "exceeds" in err["error"]


def test_resume_file_unknown_keys_rejected(run_cb, claw_home):
    bad = claw_home / "bad.json"
    bad.write_text(json.dumps({"summary": "ok", "evil_key": "payload"}))

    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--resume-file", str(bad))
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert "unknown keys" in err["error"]


def test_resume_json_non_object_rejected(run_cb):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--resume-json", '"just a string"')
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert "must be a JSON object" in err["error"]


def test_resume_json_unknown_keys_rejected(run_cb):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b",
               "--resume-json", json.dumps({"summary": "ok", "sneaky": 1}))
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert "unknown keys" in err["error"]


def test_resume_json_wrong_type_field_rejected(run_cb):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b",
               "--resume-json", json.dumps({"steps": "not-a-list"}))
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert "resume.steps" in err["error"]


def test_resume_flags_still_work_unvalidated_shape(run_cb):
    """--summary/--step/etc build a trusted dict directly; T7's schema check
    only guards the untrusted --resume-json/--resume-file paths."""
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b",
               "--summary", "s", "--step", "one", "--step", "two",
               "--expects", "x", "--integrate", "y")
    assert r.returncode == 0
