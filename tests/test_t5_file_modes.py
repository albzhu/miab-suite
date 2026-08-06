"""
T5 — harden file modes. [S2]

State used to be created 755/644, inheriting the ambient umask — world
readable on a fresh install. The process now sets umask(0o077) at entry and
explicitly chmods directories to 0700 and files to 0600, so a permissive
ambient umask must not matter.
"""
import stat

from conftest import parse_json


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_state_dir_and_files_are_0700_0600_despite_permissive_umask(run_cb, claw_home, monkeypatch):
    # Note: subprocess inherits the parent's umask; main() sets os.umask(0o077)
    # itself as the first statement, so this must hold regardless of what the
    # caller's shell umask was.
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--summary", "s")
    assert r.returncode == 0
    out = parse_json(r.stdout)
    cid = out["id"]

    cb_dir = claw_home / "state" / "callbacks"
    assert _mode(cb_dir) == 0o700
    assert _mode(cb_dir / "ledger.jsonl") == 0o600
    assert _mode(cb_dir / f"{cid}.json") == 0o600


def test_registry_file_is_0600(run_cb, claw_home):
    r = run_cb("register", "--agent", "main", "--agent-id", "agent:main")
    assert r.returncode == 0
    reg_path = claw_home / "state" / "callbacks" / "agent-registry.json"
    assert reg_path.exists()
    assert _mode(reg_path) == 0o600


def test_archive_dir_is_0700(run_cb, claw_home):
    r = run_cb("create", "--task", "t", "--from", "a", "--to", "b", "--summary", "s")
    cid = parse_json(r.stdout)["id"]
    r2 = run_cb("cancel", "--id", cid, "--from", "a")
    assert r2.returncode == 0
    archive_dir = claw_home / "state" / "callbacks" / "archive"
    assert _mode(archive_dir) == 0o700
