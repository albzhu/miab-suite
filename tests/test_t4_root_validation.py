"""
T4 — validate CLAW_HOME ownership and mode before trusting it. [S8]

A poisoned $CLAW_HOME env var can redirect all state (including
agent-registry.json, which decides where wake events route) onto an
attacker-controlled tree. The root must be owned by the current uid and
mode <= 0700, or the process must refuse to run.
"""
import os
import stat
from unittest import mock

import pytest

from conftest import parse_json


def test_overly_permissive_root_mode_is_refused(run_cb, tmp_path):
    bad_root = tmp_path / "bad_root"
    bad_root.mkdir(mode=0o777)
    os.chmod(bad_root, 0o777)   # mkdir() mode is subject to umask; force it

    r = run_cb("list", claw_home_override=bad_root)
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert err["ok"] is False
    assert "mode" in err["error"]


@pytest.mark.parametrize("mode", [0o750, 0o550, 0o540, 0o505])
def test_group_or_world_accessible_root_is_refused(run_cb, tmp_path, mode):
    """The mode check is a bitmask test (any of 0o077), not `mode > 0o700` — a
    numeric comparison lets any mode whose OWNER triad is < 7 slip through
    regardless of group/other bits (e.g. 0o550 and 0o505 are both <= 0o700
    numerically but are group- or world-readable). Every mode here keeps the
    owner execute bit set (the '5'/'7' in the leading digit) so the process can
    still traverse into the directory and the failure genuinely comes from the
    mode check, not an unrelated PermissionError."""
    bad_root = tmp_path / f"bad_root_{oct(mode)}"
    bad_root.mkdir(mode=mode)
    os.chmod(bad_root, mode)   # mkdir() mode is subject to umask; force it

    r = run_cb("list", claw_home_override=bad_root)
    assert r.returncode != 0
    err = parse_json(r.stderr)
    assert err["ok"] is False
    assert "mode" in err["error"]


def test_normal_0700_root_is_accepted(run_cb, tmp_path):
    good_root = tmp_path / "good_root"
    good_root.mkdir(mode=0o700)
    os.chmod(good_root, 0o700)

    r = run_cb("list", claw_home_override=good_root)
    assert r.returncode == 0


def test_first_run_nonexistent_root_is_not_refused(run_cb, tmp_path):
    """A CLAW_HOME that doesn't exist yet is a first run, not an attack — it's
    created under the process umask (see T5) rather than rejected outright."""
    fresh_root = tmp_path / "does_not_exist_yet"
    r = run_cb("list", claw_home_override=fresh_root)
    assert r.returncode == 0


def test_validate_root_rejects_uid_mismatch(cb_module, tmp_path):
    """White-box: _validate_root() must refuse a root owned by a different uid.
    Simulated via a mocked stat result since the sandbox has no second uid
    available to actually chown a directory to."""
    root = tmp_path / "someone_elses_root"
    root.mkdir(mode=0o700)

    real_stat = root.stat()
    fake_stat = mock.Mock(wraps=real_stat)
    fake_stat.st_uid = real_stat.st_uid + 12345
    fake_stat.st_mode = real_stat.st_mode

    with mock.patch.object(type(root), "stat", return_value=fake_stat):
        with pytest.raises(SystemExit):
            cb_module._validate_root(root)
