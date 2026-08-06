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
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]          # Skills/miab-broker
CB_SCRIPT = REPO_ROOT / "scripts" / "bin" / "claw-callback.py"

assert CB_SCRIPT.exists(), f"expected CLI at {CB_SCRIPT}"


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
