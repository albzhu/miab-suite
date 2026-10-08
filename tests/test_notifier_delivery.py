"""A failed send must be loud, and a crash must cost at most one repeat (observer 2.0.1).

`process` delivers in ledger order and stops at the first send that fails, with the cursor
parked on that bottle so the next run retries it. Two things about that used to be wrong:

  * it exited 0, so a bottle whose send never succeeds blocked every bottle behind it while
    cron saw success every time;
  * state was saved once per batch, so a kill between a send and that save re-posted the
    whole batch.

What these tests pin (the decisions Albert made for 2.0.1):

  * the first failed send in `process` stops the batch, saves the state (cursor on the
    failing bottle, earlier successes recorded) and exits 1 with the usual JSON summary on
    stdout carrying `"ok": false`, `"delivered": false` and an `error` naming the bottle;
  * a run with no failed send exits 0 and its output gains `"ok": true`;
  * `finalize` is unchanged: it already exits 1 on a failed send.

Every delivery goes to the fake `openclaw` the `notifier` fixture puts first on PATH; see
tests/conftest.py. These tests cannot reach the real CLI.
"""
import json
import subprocess
import sys

import pytest

from conftest import NOTIFY_SCRIPT, make_bottle

A = "cb-20260101000000-aaa001"
B = "cb-20260101000100-bbb002"
C = "cb-20260101000200-ccc003"

# Seven ledger lines: A is lines 0-2 (resolve at 2), B is 3-4 (cancel at 4), C is 5-6
# (fail at 6). A bottle's end record is the line its cursor parks on when its send fails.
THREE = (make_bottle(A, "resolve", t0=0)
         + make_bottle(B, "cancel", t0=10, reason="no longer needed")
         + make_bottle(C, "fail", t0=20, reason="reaped"))
TOTAL = len(THREE)
END_LINE = {A: 2, B: 4, C: 6}
ORDER = [A, B, C]

SUMMARY_KEYS = {"ok", "messages", "skipped_already_delivered", "status", "delivered"}


def _start_at_zero(notifier, ledger=THREE):
    notifier.write_ledger(ledger)
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": []})


def _attempts(notifier):
    """Every send the fake saw, in order, as (exit code, which of A..C it was about)."""
    return [(c["exit"], [x for x in ORDER if x in notifier.message_of(c)])
            for c in notifier.calls()]


# ------------------------------------------------------------------ a failed send exits 1

@pytest.mark.parametrize("failing", ORDER, ids=["first-bottle", "middle-bottle", "last-bottle"])
def test_a_failed_send_exits_1_stops_the_batch_and_the_next_run_retries(notifier, failing):
    """Whichever bottle's send fails: `process` exits 1 and says which; nothing behind it is
    attempted; the state already holds the earlier successes with the cursor on the failing
    bottle's end record; the next run (the fake now succeeding) sends it and the rest, each
    exactly once, and exits 0."""
    _start_at_zero(notifier)
    before = ORDER[:ORDER.index(failing)]
    after = ORDER[ORDER.index(failing) + 1:]

    r = notifier.run("process", exit_code=1, fail_only=failing)

    assert r.returncode == 1, (r.stdout, r.stderr)
    out = json.loads(r.stdout)                    # the summary is on stdout, not stderr
    assert out["ok"] is False
    assert out["delivered"] is False
    assert failing in out["error"]
    assert not any(other in out["error"] for other in ORDER if other != failing)
    assert set(out) == SUMMARY_KEYS | {"error"}
    assert [next(x for x in ORDER if x in m) for m in out["messages"]] == before, (
        "`messages` lists what this run did deliver")
    assert out["skipped_already_delivered"] == []

    assert _attempts(notifier) == [(0, [b]) for b in before] + [(1, [failing])], (
        f"nothing after the failing bottle may be attempted: {after}")
    state = notifier.state()
    assert state["last_processed_line"] == END_LINE[failing], "the cursor parks on that bottle"
    assert state["delivered_ids"] == before
    assert state["ledger_head"] == notifier.ledger_head()

    r = notifier.run("process")                   # the fake now succeeds for everything
    assert r.returncode == 0, r.stderr
    assert _attempts(notifier)[len(before) + 1:] == [(0, [x]) for x in [failing] + after]
    assert [x for m in notifier.messages() for x in ORDER if x in m] == ORDER, (
        "each bottle is delivered exactly once")
    state = notifier.state()
    assert state["last_processed_line"] == TOTAL
    assert state["delivered_ids"] == ORDER


def test_a_send_that_never_succeeds_is_reported_on_every_run(notifier):
    """The incident this fixes: B can never be sent, C waits behind it, and each cron run used
    to report success. Now every run fails, on B, and nothing else is retried or sent."""
    _start_at_zero(notifier)

    for _ in range(3):
        r = notifier.run("process", exit_code=1, fail_only=B)
        assert r.returncode == 1, (r.stdout, r.stderr)
        assert B in json.loads(r.stdout)["error"]
        assert notifier.state()["last_processed_line"] == END_LINE[B]
        assert notifier.state()["delivered_ids"] == [A]

    assert _attempts(notifier) == [(0, [A]), (1, [B]), (1, [B]), (1, [B])], (
        "A is sent once, B is retried each run, C is never attempted")


def test_an_openclaw_that_cannot_be_run_is_a_failed_send_too(notifier):
    """The CLI missing from PATH is the other way a send fails (the subprocess raises)."""
    _start_at_zero(notifier)
    env = notifier.env()
    (notifier.bin_dir / "openclaw").unlink()

    r = subprocess.run([sys.executable, str(NOTIFY_SCRIPT), "process"], env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=notifier.tmp_path, timeout=60)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "delivery failed" in r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is False and out["delivered"] is False and A in out["error"]
    assert notifier.calls() == []
    assert notifier.state()["last_processed_line"] == END_LINE[A]
    assert notifier.state()["delivered_ids"] == []


def test_finalize_still_exits_1_on_a_failed_send(notifier):
    """Unchanged, and the reason `process` now matches it."""
    notifier.write_ledger(THREE)
    r = notifier.run("finalize", B, exit_code=1)
    assert r.returncode == 1
    assert '"ok": false' in r.stderr          # after the "delivery failed" line deliver_one prints


# ----------------------------------------------------------- every other outcome is ok: true

def test_a_run_with_no_failed_send_exits_0_and_says_ok_true(notifier):
    _start_at_zero(notifier)

    r = notifier.run("process")

    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["delivered"] is True
    assert set(out) == SUMMARY_KEYS, "the summary keeps its keys; `ok` is the only addition"
    assert len(out["messages"]) == 3
    assert out["skipped_already_delivered"] == []
    assert "Delivered 3 closed-bottle report(s); cursor now 7/7." in out["status"]


def _seed_first_run(notifier):
    notifier.write_ledger(THREE)


def _seed_no_ledger(notifier):
    pass


def _seed_empty_ledger_with_state(notifier):
    notifier.ledger.write_text("", encoding="utf-8")
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": []})


def _seed_disabled(notifier):
    notifier.write_ledger(THREE)
    notifier.write_state({"enabled": False, "last_processed_line": 0, "delivered_ids": []})


def _seed_nothing_new(notifier):
    notifier.write_ledger(THREE)
    notifier.write_state({"enabled": True, "last_processed_line": TOTAL, "delivered_ids": []})


def _seed_only_already_delivered(notifier):
    notifier.write_ledger(THREE)
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": ORDER})


@pytest.mark.parametrize("seed", [
    pytest.param(_seed_first_run, id="first-run"),
    pytest.param(_seed_no_ledger, id="no-ledger-no-state"),
    pytest.param(_seed_empty_ledger_with_state, id="empty-ledger"),
    pytest.param(_seed_disabled, id="disabled"),
    pytest.param(_seed_nothing_new, id="nothing-new"),
    pytest.param(_seed_only_already_delivered, id="only-already-delivered"),
])
def test_every_process_outcome_that_is_not_a_failed_send_says_ok_true(notifier, seed):
    """`ok` is the field a cron wrapper reads, so it must be there whatever `process` did."""
    seed(notifier)
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["ok"] is True
    assert notifier.messages() == []
