"""notify_closed_bottles.py must never replay history by accident (observer 2.0.1).

The notifier is the one piece of this repo whose output leaves the machine, so its
dangerous failure is not crashing — it is re-posting. Until 2.0.1 `load_state()`
swallowed every exception and returned the same `{"enabled": true,
"last_processed_line": 0}` it used for a genuine first run, and `process` reset the
cursor to 0 whenever it exceeded the ledger length. A corrupt `closed_bottle_state.json`,
a missing one, or a rotated ledger therefore re-posted every closed bottle in the ledger.

What these tests pin (the decisions Albert made for 2.0.1):

  * A MISSING state file is the only fresh start, and a fresh start begins at the
    ledger END: nothing is posted, whichever command creates the state.
  * A PRESENT but unusable state file fails closed: exit 1, `ok: false` on stderr,
    nothing delivered, the file left byte-for-byte as found.
  * A cursor beyond the ledger is ambiguous (truncation vs the broker's rotation by
    rename), and the stored ledger fingerprint — `ledger_head`, the SHA-256 of the first
    non-empty ledger line — is what tells the two apart.

Every delivery goes to the fake `openclaw` the `notifier` fixture puts first on PATH;
see tests/conftest.py. These tests cannot reach the real CLI.
"""
import json

import pytest

from conftest import DRYRUN_SCRIPT, make_bottle, sha256_hex

A = "cb-20260101000000-aaa001"
B = "cb-20260101000100-bbb002"
C = "cb-20260101000200-ccc003"
D = "cb-20260101000300-ddd004"

# Seven ledger lines: A is lines 0-2 (resolve at 2), B is 3-4 (cancel at 4), C is 5-6
# (fail at 6). Cursor 3 is "everything up to and including A is processed".
THREE = (make_bottle(A, "resolve", t0=0)
         + make_bottle(B, "cancel", t0=10, reason="no longer needed")
         + make_bottle(C, "fail", t0=20, reason="reaped"))
TOTAL = len(THREE)


def _delivered_ids(notifier):
    """Which of A..D the fake received a delivered message for, in order."""
    out = []
    for msg in notifier.messages():
        out.extend(c for c in (A, B, C, D) if c in msg)
    return out


def _stderr_json(result):
    err = json.loads(result.stderr)
    assert err["ok"] is False
    return err


# ----------------------------------------------------------------------- first run

def test_missing_state_starts_at_the_ledger_end_and_posts_nothing(notifier):
    """Test 1. No state file: record where the ledger ends, say so, send nothing — then a
    bottle that closes afterwards is delivered exactly once."""
    notifier.write_ledger(THREE)

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == [], "a first run must not backfill the ledger"

    state = notifier.state()
    assert state["last_processed_line"] == TOTAL
    assert state["ledger_head"] == sha256_hex(json.dumps(THREE[0], ensure_ascii=False))
    assert state["delivered_ids"] == []
    assert state["enabled"] is True
    assert "first run" in json.loads(r.stdout)["status"].lower()
    # Atomic write, and the file keeps its name: nothing renamed, no .tmp left behind.
    assert notifier.callbacks_listing() == ["closed_bottle_state.json", "ledger.jsonl"]

    notifier.append_ledger(make_bottle(D, "resolve", t0=30))
    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [D]

    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [D], "a delivered bottle must not be posted twice"
    assert notifier.state()["last_processed_line"] == TOTAL + 3
    assert notifier.state()["delivered_ids"] == [D]


@pytest.mark.parametrize("ledger_text", [None, "", "\n  \n\n"],
                         ids=["ledger-missing", "ledger-empty", "ledger-blank-lines"])
def test_first_run_with_no_ledger_writes_nothing(notifier, ledger_text):
    """The table's last row, for a missing state file: with nothing to scan there is
    nothing to record, and a state file is not invented."""
    if ledger_text is not None:
        notifier.ledger.write_text(ledger_text, encoding="utf-8")
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == []
    assert not notifier.state_path.exists()


NO_LEDGER = pytest.mark.parametrize(
    "ledger_text", [None, "", "\n  \n\n"], ids=["ledger-missing", "ledger-empty", "ledger-blank-lines"])


@NO_LEDGER
def test_the_first_run_status_for_an_empty_ledger_names_the_gap_and_the_remedy(notifier, ledger_text):
    """Nothing is recorded when there is no ledger yet, so a bottle that closes before the
    first `process` run that sees a non-empty ledger is never posted. That is deliberate
    (see the next tests), which is exactly why the status output has to say it."""
    if ledger_text is not None:
        notifier.ledger.write_text(ledger_text, encoding="utf-8")

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    status = json.loads(r.stdout)["status"]
    assert "no state file was created" in status
    assert "will not be posted" in status
    assert "non-empty ledger" in status
    assert "`on` records the ledger start" in status
    # ... and saying so changes nothing else.
    assert not notifier.state_path.exists()
    assert notifier.calls() == []
    assert notifier.callbacks_listing() == ([] if ledger_text is None else ["ledger.jsonl"])


@NO_LEDGER
def test_a_bottle_that_closes_before_the_first_run_that_sees_a_ledger_is_not_posted(notifier, ledger_text):
    """The gap itself, pinned so that the documentation of it stays true: `process` records
    nothing for an empty ledger (a cursor of 0 there would backfill a whole history if
    CLAW_LEDGER was mistyped at first and corrected later), so the first run that does see
    a ledger starts at ITS end. Bottles that close afterwards are posted."""
    if ledger_text is not None:
        notifier.ledger.write_text(ledger_text, encoding="utf-8")
    assert notifier.run("process").returncode == 0
    assert not notifier.state_path.exists()

    notifier.write_ledger(make_bottle(A, "resolve", t0=0))              # opens and closes
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == [], "A closed before the first run that saw a ledger"
    assert notifier.state()["last_processed_line"] == 3

    notifier.append_ledger(make_bottle(B, "resolve", t0=10))
    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [B]


@NO_LEDGER
def test_running_on_first_closes_the_gap_by_recording_the_ledger_start(notifier, ledger_text):
    """The remedy the status output and SKILL.md give: `on` against a missing or empty
    ledger records cursor 0, so the first bottle to close is posted exactly once."""
    if ledger_text is not None:
        notifier.ledger.write_text(ledger_text, encoding="utf-8")
    r = notifier.run("on")
    assert r.returncode == 0, r.stderr
    assert notifier.state() == {"enabled": True, "last_processed_line": 0, "delivered_ids": []}

    notifier.write_ledger(make_bottle(A, "resolve", t0=0))
    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [A]
    assert notifier.state()["last_processed_line"] == 3
    assert notifier.state()["ledger_head"] == notifier.ledger_head()

    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [A], "and only once"


def test_on_against_a_mistyped_ledger_path_backfills_once_the_path_is_corrected(notifier):
    """Why `process` does not do for an empty ledger what `on` does, and why SKILL.md says to
    run `on` only once CLAW_LEDGER is right: a cursor of 0 recorded against the wrong path
    is a cursor of 0 against the right ledger, history and all."""
    wrong = notifier.callbacks / "typo-ledger.jsonl"                    # never created
    assert notifier.run("on", extra_env={"CLAW_LEDGER": str(wrong)}).returncode == 0
    assert notifier.state()["last_processed_line"] == 0

    notifier.write_ledger(THREE)                                         # the path, corrected
    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [A, B, C]


@pytest.mark.parametrize("command", ["on", "off"])
def test_on_and_off_against_missing_state_do_not_cause_a_later_backfill(notifier, command):
    """Test 2. `on` / `off` create the state when there is none. It must be the same
    ledger-end state `process` would have built, never a cursor-0 one that the next
    `process` backfills from."""
    notifier.write_ledger(THREE)

    r = notifier.run(command)
    assert r.returncode == 0, r.stderr
    state = notifier.state()
    assert state["enabled"] is (command == "on")
    assert state["last_processed_line"] == TOTAL
    assert state["ledger_head"] == notifier.ledger_head()
    assert state["delivered_ids"] == []

    if command == "off":
        assert notifier.run("on").returncode == 0
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == [], "a later process backfilled the ledger"

    notifier.append_ledger(make_bottle(D, "cancel", t0=30, reason="late"))
    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [D]


def test_finalize_against_missing_state_does_not_cause_a_later_backfill(notifier):
    """Test 2, third path. `finalize <cid>` posts one older bottle on demand, and its
    dedup bookkeeping creates the state: ledger-end cursor, not cursor 0."""
    notifier.write_ledger(THREE)

    r = notifier.run("finalize", B)
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [B]
    state = notifier.state()
    assert state["delivered_ids"] == [B]
    assert state["last_processed_line"] == TOTAL
    assert state["ledger_head"] == notifier.ledger_head()
    assert state["enabled"] is True

    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [B], "A and C were backfilled after finalize"

    # And finalize stays exactly-once.
    r = notifier.run("finalize", B)
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [B]


def test_failed_finalize_leaves_no_state_behind(notifier):
    """A delivery that fails must not leave a state file for a later run to trust."""
    notifier.write_ledger(THREE)
    r = notifier.run("finalize", B, exit_code=1)
    assert r.returncode == 1
    assert not notifier.state_path.exists()


# --------------------------------------------------------------- unusable state files

UNUSABLE_STATES = [
    # unreadable / not JSON
    pytest.param(b'{"enabled": true, "last_proc', id="truncated-mid-write"),
    pytest.param(b"", id="empty-file"),
    pytest.param(b"not json at all", id="not-json"),
    pytest.param(b"\xff\xfe\x00\x80", id="not-utf8"),
    # JSON, but not an object
    pytest.param(b"[1, 2, 3]", id="array"),
    pytest.param(b"null", id="json-null"),
    pytest.param(b'"text"', id="json-string"),
    pytest.param(b"42", id="json-number"),
    # last_processed_line
    pytest.param(b"{}", id="cursor-absent"),
    pytest.param(b'{"enabled": true}', id="cursor-absent-with-enabled"),
    pytest.param(b'{"last_processed_line": -5}', id="cursor-negative"),
    pytest.param(b'{"last_processed_line": "12"}', id="cursor-string"),
    pytest.param(b'{"last_processed_line": 1.5}', id="cursor-float"),
    pytest.param(b'{"last_processed_line": true}', id="cursor-bool-true"),
    pytest.param(b'{"last_processed_line": false}', id="cursor-bool-false"),
    pytest.param(b'{"last_processed_line": null}', id="cursor-null"),
    # delivered_ids present but not a list of strings
    pytest.param(b'{"last_processed_line": 0, "delivered_ids": "cb-1"}', id="delivered-string"),
    pytest.param(b'{"last_processed_line": 0, "delivered_ids": {"a": 1}}', id="delivered-object"),
    pytest.param(b'{"last_processed_line": 0, "delivered_ids": null}', id="delivered-null"),
    pytest.param(b'{"last_processed_line": 0, "delivered_ids": [1, 2]}', id="delivered-ints"),
    pytest.param(b'{"last_processed_line": 0, "delivered_ids": ["cb-1", null]}',
                 id="delivered-mixed"),
    # enabled present but not a bool
    pytest.param(b'{"last_processed_line": 0, "enabled": "yes"}', id="enabled-string"),
    pytest.param(b'{"last_processed_line": 0, "enabled": 1}', id="enabled-one"),
    pytest.param(b'{"last_processed_line": 0, "enabled": 0}', id="enabled-zero"),
    pytest.param(b'{"last_processed_line": 0, "enabled": null}', id="enabled-null"),
    # ledger_head (new in 2.0.1): optional, but if present it must be a SHA-256 hex digest.
    # A garbage fingerprint would otherwise read as "a different ledger" and backfill.
    pytest.param(b'{"last_processed_line": 0, "ledger_head": 5}', id="head-int"),
    pytest.param(b'{"last_processed_line": 0, "ledger_head": null}', id="head-null"),
    pytest.param(b'{"last_processed_line": 0, "ledger_head": "abc"}', id="head-not-a-digest"),
]


def _invoke(notifier, command):
    return notifier.run(command, B) if command == "finalize" else notifier.run(command)


def _assert_refused(notifier, result, before_bytes, before_listing):
    assert result.returncode == 1, (
        f"expected exit 1, got {result.returncode}. stdout={result.stdout!r}")
    assert result.stdout.strip() == "", "a refusal should print nothing to stdout"
    err = _stderr_json(result)
    assert "state_file" in err and "remedy" in err
    assert notifier.calls() == [], "something was delivered despite the refusal"
    assert notifier.state_path.read_bytes() == before_bytes, "the state file was rewritten"
    assert notifier.callbacks_listing() == before_listing, "the refusal wrote a stray file"


@pytest.mark.parametrize("command", ["process", "on", "finalize"])
@pytest.mark.parametrize("state_bytes", UNUSABLE_STATES)
def test_unusable_state_fails_closed(notifier, command, state_bytes):
    """Test 3. A present-but-unusable state file exits 1 and touches nothing. With the
    ledger holding three closed bottles, any fall-through to cursor 0 would post them."""
    notifier.write_ledger(THREE)
    notifier.write_state_bytes(state_bytes)
    listing = notifier.callbacks_listing()

    r = _invoke(notifier, command)
    _assert_refused(notifier, r, state_bytes, listing)


@pytest.mark.parametrize("command", ["peek", "status", "off"])
def test_other_state_commands_also_fail_closed(notifier, command):
    notifier.write_ledger(THREE)
    damaged = b'{"enabled": true, "last_proc'
    notifier.write_state_bytes(damaged)
    listing = notifier.callbacks_listing()

    _assert_refused(notifier, _invoke(notifier, command), damaged, listing)


@pytest.mark.parametrize("command", ["process", "on", "finalize"])
def test_a_state_path_that_cannot_be_read_fails_closed(notifier, command):
    """The 'unreadable' case, made deterministic (chmod 000 does nothing as root): the
    state path is a directory, so open() raises OSError rather than returning bytes."""
    notifier.write_ledger(THREE)
    notifier.state_path.mkdir()
    listing = notifier.callbacks_listing()

    r = _invoke(notifier, command)
    assert r.returncode == 1, r.stdout
    _stderr_json(r)
    assert notifier.calls() == []
    assert notifier.state_path.is_dir()
    assert notifier.callbacks_listing() == listing


def test_render_and_dryrun_do_not_need_state(notifier):
    """`render` and the dry-run script read the ledger only; a corrupt state file must
    not stop an operator from seeing what would be sent."""
    notifier.write_ledger(THREE)
    notifier.write_state_bytes(b"not json at all")

    r = notifier.run("render", B)
    assert r.returncode == 0, r.stderr
    assert B in r.stdout

    r = notifier.run(B, script=DRYRUN_SCRIPT)
    assert r.returncode == 0, r.stderr
    assert B in r.stdout

    assert notifier.state_path.read_bytes() == b"not json at all"
    assert notifier.calls() == []


# ----------------------------------------------------------------------------- control

def test_intact_2_0_0_state_is_honoured(notifier):
    """Test 4, the control that keeps the guards above from being vacuous. A 2.0.0-shaped
    state (no `ledger_head`) with a mid-ledger cursor resumes exactly there: A is before
    the cursor and is not re-posted, B is after it and is, and C is after it but already
    in `delivered_ids` (what `finalize` leaves behind) and is skipped."""
    notifier.write_state({"enabled": True, "last_processed_line": 3, "delivered_ids": [C]})
    notifier.write_ledger(THREE)

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [B]

    state = notifier.state()
    assert state["last_processed_line"] == TOTAL
    assert state["delivered_ids"] == [C, B]
    assert state["enabled"] is True
    assert state["ledger_head"] == notifier.ledger_head(), "the fingerprint is adopted"

    status = json.loads(notifier.run("status").stdout)
    assert status["last_processed_line"] == TOTAL


def test_a_disabled_notifier_delivers_nothing(notifier):
    notifier.write_state({"enabled": False, "last_processed_line": 0, "delivered_ids": []})
    notifier.write_ledger(THREE)
    assert notifier.run("process").returncode == 0
    assert notifier.calls() == []


# ----------------------------------------------------- cursor versus ledger (the table)

def _seed(notifier, *, cursor, head="current", delivered=(), ledger=THREE):
    """Write the ledger and a state file whose fingerprint is `head`:
    "current" = the ledger's own, "other" = a valid digest of some other ledger,
    "absent" = a 2.0.0 state with no ledger_head key."""
    if ledger is not None:
        notifier.write_ledger(ledger)
    state = {"enabled": True, "last_processed_line": cursor, "delivered_ids": list(delivered)}
    if head == "current":
        state["ledger_head"] = notifier.ledger_head()
    elif head == "other":
        state["ledger_head"] = sha256_hex("the first line of some other ledger")
    else:
        assert head == "absent"
    notifier.write_state(state)
    return state


def test_same_head_cursor_within_ledger_is_normal(notifier):
    _seed(notifier, cursor=3)
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [B, C]
    state = notifier.state()
    assert state["last_processed_line"] == TOTAL
    assert state["ledger_head"] == notifier.ledger_head()


def test_same_head_cursor_at_ledger_end_has_nothing_to_do(notifier):
    before = _seed(notifier, cursor=TOTAL)
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == []
    assert notifier.state() == before


@pytest.mark.parametrize("command", ["process", "peek"])
def test_same_head_cursor_beyond_ledger_is_truncation(notifier, command):
    """Same first line, fewer lines than the cursor: the ledger was cut, not replaced.
    Exit 1, nothing delivered, state untouched — and `peek` reads the same verdict."""
    _seed(notifier, cursor=TOTAL + 5)
    before = notifier.state_path.read_bytes()
    listing = notifier.callbacks_listing()

    r = notifier.run(command)
    _assert_refused(notifier, r, before, listing)
    assert "truncat" in json.loads(r.stderr)["error"].lower()


@pytest.mark.parametrize("cursor", [TOTAL + 5, 3], ids=["cursor-beyond-ledger", "cursor-in-range"])
def test_different_head_is_a_new_ledger_and_starts_at_line_zero(notifier, cursor):
    """The broker rotates by renaming ledger.jsonl, so a different first line means a new
    ledger whatever the old cursor says. Start at 0, record the new fingerprint, and let
    `delivered_ids` dedup: B is already delivered, so A and C go out.

    With cursor 3 an implementation that kept the old cursor would post C only — A is
    what proves the scan began at line 0."""
    _seed(notifier, cursor=cursor, head="other", delivered=[B])

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [A, C]
    state = notifier.state()
    assert state["last_processed_line"] == TOTAL
    assert state["ledger_head"] == notifier.ledger_head()
    assert state["delivered_ids"] == [B, A, C]
    status = json.loads(r.stdout)["status"].lower()
    assert "new ledger" in status


def test_peek_on_a_new_ledger_reads_from_line_zero_and_writes_nothing(notifier):
    _seed(notifier, cursor=TOTAL + 5, head="other", delivered=[B])
    before = notifier.state_path.read_bytes()

    r = notifier.run("peek")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert [A in m for m in out["messages"]] == [True, False], (
        "peek must show what process would send: A and C, not the already-delivered B")
    assert C in out["messages"][1]
    assert out["delivered"] is False
    assert notifier.state_path.read_bytes() == before
    assert notifier.calls() == []


def test_absent_head_with_cursor_in_range_adopts_the_head_and_continues(notifier):
    """A 2.0.0 state file. Its cursor is believable, so keep it and learn the fingerprint."""
    _seed(notifier, cursor=3, head="absent")
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [B, C]
    state = notifier.state()
    assert state["ledger_head"] == notifier.ledger_head()
    assert state["last_processed_line"] == TOTAL


def test_absent_head_is_adopted_even_when_there_is_nothing_new(notifier):
    """If the fingerprint were only written when something was delivered, a quiet 2.0.0
    install would stay unprotected against truncation until its next bottle."""
    _seed(notifier, cursor=TOTAL, head="absent")
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == []
    state = notifier.state()
    assert state["ledger_head"] == notifier.ledger_head()
    assert state["last_processed_line"] == TOTAL


@pytest.mark.parametrize("command", ["process", "peek"])
def test_absent_head_with_cursor_beyond_ledger_is_ambiguous(notifier, command):
    """Truncated or rotated? Without a fingerprint there is no telling, so refuse and
    hand the operator a remedy rather than guess."""
    _seed(notifier, cursor=TOTAL + 1, head="absent")
    before = notifier.state_path.read_bytes()
    listing = notifier.callbacks_listing()

    r = notifier.run(command)
    _assert_refused(notifier, r, before, listing)
    err = json.loads(r.stderr)
    assert "ambiguous" in err["error"].lower()
    assert "ledger_head" in err["remedy"] or "last_processed_line" in err["remedy"]


@pytest.mark.parametrize("ledger", [None, "", "\n \n"],
                         ids=["ledger-missing", "ledger-empty", "ledger-blank-lines"])
@pytest.mark.parametrize("head", ["current", "other", "absent"])
def test_a_missing_or_empty_ledger_is_a_no_op_that_leaves_state_alone(notifier, ledger, head):
    """The broker's rotation leaves a window with no ledger at all. Whatever the state
    says, that window must not deliver, reset or rewrite anything."""
    # "current" can only be seeded once there is a ledger to fingerprint.
    notifier.write_ledger(THREE)
    _seed(notifier, cursor=TOTAL, head=head, delivered=[A], ledger=None)
    if ledger is None:
        notifier.ledger.unlink()
    else:
        notifier.ledger.write_text(ledger, encoding="utf-8")
    before = notifier.state_path.read_bytes()

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert notifier.calls() == []
    assert notifier.state_path.read_bytes() == before


def test_truncation_is_detected_after_a_first_run(notifier):
    """End to end: the fingerprint written by a first run is what later catches a cut."""
    notifier.write_ledger(THREE)
    assert notifier.run("process").returncode == 0
    before = notifier.state_path.read_bytes()

    notifier.write_ledger(THREE[:4])         # same first line, three lines short
    r = notifier.run("process")
    assert r.returncode == 1
    assert _stderr_json(r)["state_file"]
    assert notifier.state_path.read_bytes() == before
    assert notifier.calls() == []


def test_rotation_is_followed_after_a_first_run(notifier):
    """End to end: the broker renames the ledger away and starts a fresh one. The first
    run's fingerprint no longer matches, so the new ledger is read from its first line."""
    notifier.write_ledger(THREE)
    assert notifier.run("process").returncode == 0

    notifier.write_ledger(make_bottle(D, "resolve", t0=600))      # shorter than the old cursor
    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [D]
    assert notifier.state()["ledger_head"] == notifier.ledger_head()
    assert notifier.state()["last_processed_line"] == 3

    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [D]


# ------------------------------------------------------------------- delivery failure

def test_delivery_failure_stops_the_cursor_and_the_next_run_retries(notifier):
    """Test 6. A fails nowhere, B's send fails, C is never attempted this run. The cursor
    parks on B's record; the next run retries B and then sends C, and A — delivered the
    first time — is not sent again."""
    _seed(notifier, cursor=0)

    failed = notifier.run("process", exit_code=1, fail_only=B)
    # A failed send parks the cursor and is retried, and (since 2.0.1) makes `process` exit 1
    # like `finalize`, so that cron sees a bottle that is blocking the queue. The full
    # contract is pinned in tests/test_notifier_delivery.py.
    assert failed.returncode == 1, failed.stderr
    attempts = [(c["exit"], [x for x in (A, B, C) if x in notifier.message_of(c)])
                for c in notifier.calls()]
    assert attempts == [(0, [A]), (1, [B])], "C must not be attempted after B fails"

    state = notifier.state()
    assert state["last_processed_line"] == 4, "the cursor must stop at B's end record"
    assert state["delivered_ids"] == [A]

    r = notifier.run("process")                  # the fake now succeeds for everything
    assert r.returncode == 0, r.stderr
    attempts = [(c["exit"], [x for x in (A, B, C) if x in notifier.message_of(c)])
                for c in notifier.calls()]
    assert attempts == [(0, [A]), (1, [B]), (0, [B]), (0, [C])]
    assert _delivered_ids(notifier) == [A, B, C], "each bottle is delivered exactly once"
    state = notifier.state()
    assert state["last_processed_line"] == TOTAL
    assert state["delivered_ids"] == [A, B, C]


def test_delivery_failure_on_the_first_bottle_keeps_the_cursor_in_place(notifier):
    _seed(notifier, cursor=3, delivered=[])
    notifier.run("process", exit_code=1)
    assert len(notifier.calls()) == 1
    assert notifier.messages() == []
    assert notifier.state()["last_processed_line"] == 4
    assert notifier.state()["delivered_ids"] == []

    assert notifier.run("process").returncode == 0
    assert _delivered_ids(notifier) == [B, C]


def test_finalize_can_post_a_bottle_from_a_rotated_archive(notifier):
    """SKILL.md section 3a says bottles that closed in a ledger the broker has since rotated
    away are not posted by the rotation path, and that pointing CLAW_LEDGER at the archive
    for one `finalize <cid>` posts one. That has to stay true, and finalize must do it
    without disturbing the cursor that now belongs to the new ledger."""
    notifier.write_ledger(THREE)
    assert notifier.run("process").returncode == 0           # first run: cursor 7, head of THREE
    archive = notifier.callbacks / "ledger.20260101000000.jsonl"
    notifier.ledger.rename(archive)                          # what the broker's rotation does
    notifier.write_ledger(make_bottle(D, "resolve", t0=600))

    assert notifier.run("process").returncode == 0           # follows the new ledger from line 0
    assert _delivered_ids(notifier) == [D]
    state_before = notifier.state()

    r = notifier.run("finalize", B, extra_env={"CLAW_LEDGER": str(archive)})
    assert r.returncode == 0, r.stderr
    assert _delivered_ids(notifier) == [D, B]
    state = notifier.state()
    assert state["delivered_ids"] == [D, B]
    assert state["last_processed_line"] == state_before["last_processed_line"]
    assert state["ledger_head"] == state_before["ledger_head"]


# ------------------------------------------------- read-only commands before a first run

def test_status_and_peek_before_a_first_run_report_it_and_write_nothing(notifier):
    """`status` and `peek` with no state file say what a real `process` would do, without
    creating the state file themselves."""
    notifier.write_ledger(THREE)

    status = notifier.run("status")
    assert status.returncode == 0, status.stderr
    out = json.loads(status.stdout)
    assert out["state_present"] is False
    assert out["ledger_lines"] == TOTAL and out["last_processed_line"] == TOTAL
    assert "first run" in out["note"].lower()

    peek = notifier.run("peek")
    assert peek.returncode == 0, peek.stderr
    out = json.loads(peek.stdout)
    assert out["messages"] == [] and out["delivered"] is False
    assert "first run" in out["status"].lower()

    assert not notifier.state_path.exists()
    assert notifier.calls() == []
