"""
Shared fixtures for the claw-callback.py regression suite (M1, T3).

Tests invoke the CLI as a subprocess against a throwaway CLAW_HOME (never
production state under ~/.openclaw/), matching how the CLI is actually used
and exercising the real process-boundary behaviour (umask, exit codes,
stderr shape) rather than mocking it away.

A handful of white-box tests import the module directly to exercise
internal helpers (_validate_root, ID_RE, validate_resume_shape) that are
awkward to drive purely through the CLI surface.
"""
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]          # the combined repo root
BROKER_ROOT = REPO_ROOT / "miab-broker"                  # the writer skill
IQ_ROOT = REPO_ROOT / "miab-observer"                    # the reader skill
CB_SCRIPT = BROKER_ROOT / "scripts" / "bin" / "claw-callback.py"
IQ_SCRIPT = IQ_ROOT / "scripts" / "miab_observer.py"
NOTIFY_SCRIPT = IQ_ROOT / "scripts" / "notify_closed_bottles.py"
DRYRUN_SCRIPT = IQ_ROOT / "scripts" / "notify_closed_dryrun.py"

# Both skills live in this repo. A missing one is a broken checkout, not a
# reason to skip: the whole point of combining the trees (ADR-001) was to make
# the writer/reader contract testable unconditionally.
assert CB_SCRIPT.exists(), f"expected broker CLI at {CB_SCRIPT}"
assert IQ_SCRIPT.exists(), f"expected reader CLI at {IQ_SCRIPT}"
assert NOTIFY_SCRIPT.exists(), f"expected message-sink notifier at {NOTIFY_SCRIPT}"
assert DRYRUN_SCRIPT.exists(), f"expected notifier dry-run script at {DRYRUN_SCRIPT}"


@pytest.fixture
def claw_home(tmp_path):
    """A throwaway CLAW_HOME, owned by us, mode 0700 — the state T4 requires."""
    d = tmp_path / "claw_home"
    d.mkdir(mode=0o700)
    return d


@pytest.fixture
def run_cb(claw_home):
    """Invoke claw-callback.py as a subprocess against `claw_home`.

    Returns the CompletedProcess. Use `.json()` monkeypatch-style via `parse_json`
    below, or read `.stdout` / `.stderr` / `.returncode` directly.
    """
    def _run(*args, env_overrides=None, cwd=None, claw_home_override=None):
        env = os.environ.copy()
        env["CLAW_HOME"] = str(claw_home_override if claw_home_override is not None else claw_home)
        # Belt-and-braces: the suite resolves ~40 bottles per run. If any build of
        # the CLI ever grows an end-state notifier hook again (held back to T23),
        # this keeps `pytest` from posting fixture data to a real chat channel on
        # a dev host that happens to have the sender on PATH.
        env.setdefault("CLAW_NO_NOTIFY", "1")
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(CB_SCRIPT), *args],
            capture_output=True, text=True, env=env, cwd=cwd,
        )
    return _run


def parse_json(text: str) -> dict:
    return json.loads(text)


@pytest.fixture(scope="session")
def cb_module():
    """Import claw-callback.py as a plain module for white-box unit tests.

    Only used for pure functions with no filesystem side effects that depend
    on CLAW_HOME being pre-validated (root_dir() itself is lru_cache'd and
    process-global, so it is deliberately NOT exercised here — every test
    that needs a validated root goes through `run_cb` as a fresh subprocess).
    """
    spec = importlib.util.spec_from_file_location("claw_callback_module", CB_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Message-sink harness (notify_closed_bottles.py / notify_closed_dryrun.py)
#
# The notifier's one job is to run `openclaw message send`, so the harness's one
# invariant is that THE REAL CLI CAN NEVER BE REACHED from a test:
#   * the subprocess PATH is exactly one directory, under pytest's tmp_path, that
#     holds a fake `openclaw` — there is no second PATH entry for the real one to
#     live in, and the fixture asserts the lookup lands on the fake;
#   * HOME is a throwaway too, and every ambient CLAW_* / LYRA_* / OPENCLAW_*
#     variable is dropped, so a developer's real ledger, state file, target or
#     account can never leak into a run;
#   * the delivery target is synthetic.
# The fake appends its argv (and the exit code it chose) to a JSONL file and exits
# with FAKE_OPENCLAW_EXIT, optionally only for calls whose argv contains
# FAKE_OPENCLAW_FAIL_ONLY, so a test can assert both "nothing was sent" and
# "this one delivery failed".
# ---------------------------------------------------------------------------
SYNTHETIC_TARGET = "channel:100000000000000001"

_FAKE_OPENCLAW_PY = """\
import json
import os
import sys

argv = sys.argv[1:]
code = int(os.environ.get("FAKE_OPENCLAW_EXIT", "0"))
only = os.environ.get("FAKE_OPENCLAW_FAIL_ONLY")
if only and not any(only in a for a in argv):
    code = 0
with open(os.environ["FAKE_OPENCLAW_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "exit": code}) + "\\n")
if code:
    sys.stderr.write("fake openclaw: simulated delivery failure\\n")
sys.exit(code)
"""

_SCRUBBED_ENV_PREFIXES = ("CLAW_", "LYRA_", "OPENCLAW_", "FAKE_OPENCLAW_")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_bottle(cid, end="resolve", *, t0=0, task="synthetic task", **end_fields):
    """Ledger records for one bottle that reaches `end` (resolve / cancel / fail).

    resolve -> create, return, resolve (3 lines); cancel / fail -> create, end (2).
    `at` is unique per record (t0 + position) so the first line of a ledger differs
    from the first line of any other ledger built with a different t0.
    """
    def at(n):
        return f"2026-01-01T00:{(t0 + n) // 60 % 60:02d}:{(t0 + n) % 60:02d}Z"

    recs = [{"at": at(0), "id": cid, "event": "create", "by": "main", "to": "planner",
             "task": task}]
    if end == "resolve":
        recs.append({"at": at(1), "id": cid, "event": "return", "by": "planner",
                     "wake": "main"})
    recs.append({"at": at(len(recs)), "id": cid, "event": end, "by": "main", **end_fields})
    return recs


class NotifierHarness:
    """Drive notify_closed_bottles.py / notify_closed_dryrun.py as subprocesses."""

    def __init__(self, tmp_path, claw_home):
        self.tmp_path = tmp_path
        self.claw_home = claw_home
        self.callbacks = claw_home / "state" / "callbacks"
        self.callbacks.mkdir(parents=True)
        self.ledger = self.callbacks / "ledger.jsonl"
        self.state_path = self.callbacks / "closed_bottle_state.json"
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin_dir = tmp_path / "fakebin"
        self.bin_dir.mkdir()
        self.calls_log = tmp_path / "openclaw_calls.jsonl"

        fake_py = self.bin_dir / "fake_openclaw.py"
        fake_py.write_text(_FAKE_OPENCLAW_PY, encoding="utf-8")
        # A /bin/sh wrapper, not a `#!python` shebang: shebang length limits would
        # break on a long sys.executable path, and `#!/usr/bin/env` would need PATH.
        wrapper = self.bin_dir / "openclaw"
        wrapper.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(fake_py))} \"$@\"\n",
            encoding="utf-8")
        wrapper.chmod(0o755)

        assert tmp_path in self.bin_dir.parents
        found = shutil.which("openclaw", path=str(self.bin_dir))
        assert found == str(wrapper), f"fake openclaw not first on PATH: {found}"

    # -- environment ----------------------------------------------------------
    def env(self, *, exit_code=0, fail_only=None, extra=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(_SCRUBBED_ENV_PREFIXES)}
        env.update({
            "HOME": str(self.home),
            "PATH": str(self.bin_dir),            # the fake, and nothing else
            "CLAW_HOME": str(self.claw_home),
            "CLAW_CLOSED_TARGET": SYNTHETIC_TARGET,
            "FAKE_OPENCLAW_LOG": str(self.calls_log),
            "FAKE_OPENCLAW_EXIT": str(exit_code),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        })
        if fail_only is not None:
            env["FAKE_OPENCLAW_FAIL_ONLY"] = fail_only
        if extra:
            env.update(extra)
        assert shutil.which("openclaw", path=env["PATH"]) == str(self.bin_dir / "openclaw")
        return env

    def run(self, *args, script=NOTIFY_SCRIPT, exit_code=0, fail_only=None, extra_env=None):
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, encoding="utf-8", cwd=self.tmp_path, timeout=60,
            env=self.env(exit_code=exit_code, fail_only=fail_only, extra=extra_env))

    # -- ledger ---------------------------------------------------------------
    def write_ledger(self, records):
        self.write_ledger_lines([json.dumps(r, ensure_ascii=False) for r in records])

    def write_ledger_lines(self, lines):
        self.ledger.write_text("".join(l + "\n" for l in lines), encoding="utf-8")

    def append_ledger(self, records):
        with self.ledger.open("a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def ledger_head(self):
        """SHA-256 of the first non-empty ledger line — the fingerprint under test."""
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return sha256_hex(line.strip())
        return None

    # -- state ----------------------------------------------------------------
    def write_state(self, state: dict):
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def write_state_bytes(self, data: bytes):
        self.state_path.write_bytes(data)

    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def callbacks_listing(self):
        return sorted(os.listdir(self.callbacks))

    # -- what the fake openclaw saw ------------------------------------------
    def calls(self):
        """Every `openclaw` invocation, in order: {"argv": [...], "exit": int}."""
        if not self.calls_log.exists():
            return []
        return [json.loads(l) for l in
                self.calls_log.read_text(encoding="utf-8").splitlines() if l.strip()]

    @staticmethod
    def message_of(call):
        argv = call["argv"]
        return argv[argv.index("--message") + 1]

    def messages(self, *, delivered_only=True):
        """The `--message` argv values the fake received (by default only the calls
        that exited 0, i.e. the ones the notifier counted as delivered)."""
        return [self.message_of(c) for c in self.calls()
                if not delivered_only or c["exit"] == 0]


@pytest.fixture
def notifier(tmp_path, claw_home):
    return NotifierHarness(tmp_path, claw_home)
