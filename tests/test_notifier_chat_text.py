"""Everything the notifier posts is ledger text, and the ledger is not trusted input.

Task, result, reason, agent names, event names and the bottle id all come from records
that any agent (or anything with write access to the ledger) can author, and they are
posted to a chat channel. Until 2.0.1 `sanitize()` only collapsed whitespace and cut to a
length; `reason` skipped it entirely, and nothing neutralised `@everyone`, `@here`,
`<@…>`, `<@&…>`, `<#…>` or masked links. These tests pin the behaviour that replaced it:

  * one neutralising function, applied to EVERY ledger-derived string;
  * per-field caps (task 300, result 400, reason 300, names 64, counted in characters) and
    a cap of 1900 UTF-16 code units on the whole message -- never fewer than its characters,
    so the cap holds whichever way the receiving end counts -- with an explicit marker when
    history lines are dropped.

They assert on the `--message` argv the fake `openclaw` received — the text that would
actually have left the machine — never on a helper's return value. They say nothing
about how Discord renders that text; that needs a live send.
"""
import importlib.util
import json
import re
import unicodedata

import pytest

from conftest import NOTIFY_SCRIPT, make_bottle

ZWSP = "\u200b"
CID = "cb-20260101000000-aaa001"
OTHER = "cb-20260101000100-bbb002"

# (payload, what it must become). U+200B goes after every `@` and `<`, and `](` is split.
PAYLOADS = [
    pytest.param("@everyone", f"@{ZWSP}everyone", id="everyone"),
    pytest.param("@here", f"@{ZWSP}here", id="here"),
    pytest.param("<@123>", f"<{ZWSP}@{ZWSP}123>", id="user-mention"),
    pytest.param("<@!123>", f"<{ZWSP}@{ZWSP}!123>", id="nickname-mention"),
    pytest.param("<@&123>", f"<{ZWSP}@{ZWSP}&123>", id="role-mention"),
    pytest.param("<#123>", f"<{ZWSP}#123>", id="channel-mention"),
    pytest.param("[x](http://y)", f"[x]{ZWSP}(http://y)", id="masked-link"),
]


# Each scenario puts the payload in ONE ledger-derived field of an otherwise ordinary
# bottle. They cover the three end states, the agent names rendered through who(), every
# `reason`, the names in history lines, an unknown event name, and the bottle id itself.
def _resolve_task_on_end(p):
    recs = make_bottle(CID, "resolve", task="plain")
    recs[-1]["task"] = p                      # the end record's own task wins over create's
    return recs


def _resolve_task_on_create(p):
    return make_bottle(CID, "resolve", task=p)


def _resolve_result(p):
    return make_bottle(CID, "resolve", result=p)


def _resolve_end_agent(p):
    return make_bottle(CID, "resolve", by=p)


def _create_to_agent(p):
    recs = make_bottle(CID, "resolve")
    recs[0]["to"] = p
    return recs


def _return_wake_agent(p):
    recs = make_bottle(CID, "resolve")
    recs[1]["wake"] = p
    return recs


def _return_by_agent(p):
    recs = make_bottle(CID, "resolve")
    recs[1]["by"] = p
    return recs


def _forward_agents(p):
    recs = make_bottle(CID, "resolve")
    recs.insert(1, {"at": "2026-01-01T00:00:30Z", "id": CID, "event": "forward",
                    "by": p, "to": p})
    return recs


def _unknown_event(p):
    recs = make_bottle(CID, "resolve")
    recs.insert(1, {"at": "2026-01-01T00:00:30Z", "id": CID, "event": p, "by": "main"})
    return recs


def _corrupt_reason(p):
    recs = make_bottle(CID, "resolve")
    recs.insert(1, {"at": "2026-01-01T00:00:30Z", "id": CID, "event": "corrupt",
                    "by": "system", "reason": p})
    return recs


def _bottle_id(p):
    return make_bottle(f"cb-1-{p}", "resolve")


def _cancel_task(p):
    return make_bottle(CID, "cancel", task=p, reason="r")


def _cancel_reason(p):
    return make_bottle(CID, "cancel", reason=p)


def _cancel_agent(p):
    return make_bottle(CID, "cancel", by=p, reason="r")


def _fail_task(p):
    return make_bottle(CID, "fail", task=p, reason="r")


def _fail_reason(p):
    return make_bottle(CID, "fail", reason=p)


def _fail_agent(p):
    return make_bottle(CID, "fail", by=p, reason="r")


SCENARIOS = [
    pytest.param(_resolve_task_on_end, id="resolve-task-on-end-record"),
    pytest.param(_resolve_task_on_create, id="resolve-task-from-create"),
    pytest.param(_resolve_result, id="resolve-result"),
    pytest.param(_resolve_end_agent, id="resolve-agent-name"),
    pytest.param(_create_to_agent, id="history-create-to"),
    pytest.param(_return_wake_agent, id="history-return-wake"),
    pytest.param(_return_by_agent, id="history-return-by"),
    pytest.param(_forward_agents, id="history-forward-by-and-to"),
    pytest.param(_unknown_event, id="history-unknown-event"),
    pytest.param(_corrupt_reason, id="history-corrupt-reason"),
    pytest.param(_bottle_id, id="bottle-id"),
    pytest.param(_cancel_task, id="cancel-task"),
    pytest.param(_cancel_reason, id="cancel-reason"),
    pytest.param(_cancel_agent, id="cancel-agent-name"),
    pytest.param(_fail_task, id="fail-task"),
    pytest.param(_fail_reason, id="fail-reason"),
    pytest.param(_fail_agent, id="fail-agent-name"),
]


def _send_via_finalize(notifier, records):
    """Post one bottle through the real notifier and return the message the fake saw."""
    notifier.write_ledger(records)
    cid = next(r["id"] for r in records if r["event"] in ("resolve", "cancel", "fail"))
    r = notifier.run("finalize", cid)
    assert r.returncode == 0, r.stderr
    sent = notifier.messages()
    assert len(sent) == 1, sent
    return sent[0]


# ----------------------------------------------------------------- neutralisation

@pytest.mark.parametrize("payload, neutralised", PAYLOADS)
@pytest.mark.parametrize("build", SCENARIOS)
def test_ledger_text_is_neutralised_in_every_field(notifier, build, payload, neutralised):
    """Test 7. field x payload, for resolve, cancel and fail, history lines and agent names."""
    msg = _send_via_finalize(notifier, build(payload))

    assert neutralised in msg, "the text should survive, neutralised, not be deleted"
    assert payload not in msg
    # The properties that matter, stated independent of the exact payload:
    assert not re.search(f"@(?!{ZWSP})", msg), "an @ without U+200B after it can ping"
    assert not re.search(f"<(?!{ZWSP})", msg), "a < without U+200B after it can mention"
    assert "](" not in msg, "a masked link survived"
    for raw in ("@everyone", "@here", "<@", "<#"):
        assert raw not in msg


def test_neutralising_is_idempotent_on_text_that_already_carries_the_marker(notifier):
    """A ledger string that already contains U+200B must not grow another one per pass."""
    msg = _send_via_finalize(
        notifier, make_bottle(CID, "resolve", result=f"@{ZWSP}everyone"))
    assert f"@{ZWSP}everyone" in msg
    assert f"@{ZWSP}{ZWSP}" not in msg


def test_control_characters_and_line_injection_are_stripped(notifier):
    """A newline in a ledger string must not forge a line of the report, and control or
    bidi-override characters must not reach chat."""
    task = "line1\n   Result: FORGED\r\n\x00\x1b[31m\x07red\u202e\u2066\tend"
    msg = _send_via_finalize(notifier, make_bottle(CID, "cancel", task=task, reason="r"))

    lines = msg.split("\n")
    assert not any(l.startswith("   Result:") for l in lines), "a forged Result: line"
    assert len([l for l in lines if l.startswith("   Task:")]) == 1
    assert "line1 Result: FORGED" in msg, "whitespace should be collapsed, not deleted"
    for ch in msg:
        assert ch == "\n" or unicodedata.category(ch) != "Cc", f"control character {ch!r}"
    for bidi in ("\u202e", "\u2066", "\u202a", "\u2069"):
        assert bidi not in msg


# -------------------------------------------------------------------- length caps

CAPS = [
    # (id, builder, field cap)
    pytest.param(lambda p: make_bottle(CID, "resolve", task=p), 300, id="task"),
    pytest.param(lambda p: make_bottle(CID, "resolve", result=p), 400, id="result"),
    pytest.param(lambda p: make_bottle(CID, "cancel", reason=p), 300, id="cancel-reason"),
    pytest.param(lambda p: make_bottle(CID, "fail", reason=p), 300, id="fail-reason"),
    pytest.param(lambda p: make_bottle(CID, "resolve", by=p), 64, id="agent-name"),
    pytest.param(lambda p: _unknown_event(p), 64, id="event-name"),
    pytest.param(lambda p: make_bottle(p, "resolve"), 64, id="bottle-id"),
]


@pytest.mark.parametrize("build, cap", CAPS)
def test_each_field_is_capped(notifier, build, cap):
    """`Q` appears nowhere in the report's own text, so the longest run of Q is the length
    of the ledger field as it reached the message."""
    msg = _send_via_finalize(notifier, build("Q" * 5000))
    longest = max(len(run) for run in re.findall("Q+", msg))
    assert cap - 3 <= longest <= cap, f"field was {longest} characters, cap is {cap}"
    assert len(msg) <= 1900


@pytest.mark.parametrize("end", ["cancel", "fail"])
def test_a_10kb_reason_cannot_push_the_message_past_the_limit(notifier, end):
    """Test 8."""
    msg = _send_via_finalize(notifier, make_bottle(CID, end, reason="x" * 10_000))
    assert len(msg) <= 1900


def test_the_whole_message_is_capped_and_says_when_history_was_dropped(notifier):
    """A long delegation chain with every field at its cap. History is what gets cut, and
    the cut is announced rather than silent."""
    recs = make_bottle(CID, "resolve", task="T" * 5000, result="R" * 5000)
    for i in range(60):
        recs.insert(1, {"at": f"2026-01-01T00:01:{i:02d}Z", "id": CID, "event": "forward",
                        "by": f"n{i}-" + "N" * 5000, "to": f"m{i}-" + "M" * 5000})
    msg = _send_via_finalize(notifier, recs)

    assert len(msg) <= 1900
    assert re.search(r"\d+ more history line\(s\) omitted", msg), "no truncation marker"
    assert msg.startswith("✅ [MIAB Bottle Resolved]"), "the header must survive"
    assert "   Task: " in msg and "   Result: " in msg and "   Hops: " in msg
    dropped = int(re.search(r"(\d+) more history line", msg).group(1))
    shown = sum(1 for l in msg.split("\n") if l.startswith("     - "))
    assert dropped + shown == len(recs), "every history line is shown or counted"
    assert shown >= 1


def test_a_short_history_is_shown_in_full_with_no_marker(notifier):
    msg = _send_via_finalize(notifier, make_bottle(CID, "resolve", result="done"))
    assert "omitted" not in msg
    assert sum(1 for l in msg.split("\n") if l.startswith("     - ")) == 3


def test_known_agents_keep_their_display_names(notifier):
    """Neutralising must not eat the emoji and punctuation of AGENT_MAP / MODEL_MAP."""
    msg = _send_via_finalize(notifier, make_bottle(CID, "resolve", result="done"))
    assert "created by \u2728 LYRA (Main) [deepseek-v4-flash] -> " in msg
    assert "\U0001f977\u2694\ufe0f SPECTRE (Planner) [claude-sonnet-5]" in msg


# ----------------------------------------------------------- hostile or malformed ledgers

def test_odd_ledger_records_are_skipped_not_fatal_and_never_replayed(notifier):
    """A line that is not an object, or a record whose id / event / by is the wrong type,
    must not crash `process` part-way through a batch. A crash after a successful send
    but before the state is saved re-posts that send on every following run."""
    good_create = {"at": "2026-01-01T00:00:00Z", "id": CID, "event": "create",
                   "by": ["a", "list"], "to": {"a": "dict"}, "task": 12345}
    good_end = {"at": "2026-01-01T00:00:01Z", "id": CID, "event": "resolve",
                "by": {"k": "v"}, "result": ["a", "b"]}
    lines = [
        "[1, 2]", "5", "null", '"a string"', "not json {",
        json.dumps({"id": 7, "event": "resolve"}),
        json.dumps({"id": "", "event": "resolve"}),
        json.dumps({"id": OTHER, "event": ["resolve"]}),
        json.dumps({"id": OTHER, "event": {"x": 1}}),
        json.dumps(good_create),
        json.dumps(good_end),
    ]
    notifier.write_ledger_lines(lines)
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": []})

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    sent = notifier.messages()
    assert len(sent) == 1 and CID in sent[0], sent
    assert notifier.state()["delivered_ids"] == [CID], "state must stay loadable"
    assert notifier.state()["last_processed_line"] == len(lines)

    assert notifier.run("process").returncode == 0
    assert len(notifier.messages()) == 1


def test_a_lone_surrogate_in_the_ledger_does_not_wedge_delivery(notifier):
    """JSON permits "\\ud800". As an argv element it makes the send raise, which the
    notifier would count as a delivery failure -- forever, parking the cursor on that
    bottle and blocking every bottle behind it. It must be dropped instead."""
    lines = [json.dumps(r) for r in make_bottle(CID, "resolve", result="bad \ud800 text")]
    assert "\\ud800" in "".join(lines)
    notifier.write_ledger_lines(lines)
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": []})

    r = notifier.run("process")
    assert r.returncode == 0, r.stderr
    assert len(notifier.messages()) == 1
    assert "bad text" in notifier.messages()[0]
    assert notifier.state()["last_processed_line"] == 3


def test_process_posts_the_same_neutralised_text_finalize_does(notifier):
    """The two delivery paths share one formatter; pin that for the hostile case."""
    hostile = "@everyone <@&123> [x](http://y) " + "z" * 5000
    recs = make_bottle(CID, "cancel", task=hostile, reason=hostile)
    notifier.write_ledger(recs)
    notifier.write_state({"enabled": True, "last_processed_line": 0, "delivered_ids": []})
    assert notifier.run("process").returncode == 0
    via_process = notifier.messages()[0]

    notifier.state_path.unlink()
    assert notifier.run("finalize", CID).returncode == 0
    via_finalize = notifier.messages()[1]

    assert via_process == via_finalize
    assert len(via_process) <= 1900
    assert "@everyone" not in via_process and "<@" not in via_process


# ------------------------------------------------------- the whole-message cap, in UTF-16 units
#
# MESSAGE_LIMIT is measured in UTF-16 code units, not code points: a character outside the
# Basic Multilingual Plane (an emoji, say) is one code point and TWO units. 1826 emoji are
# 1826 characters and 3652 units, so a cap counted in characters would let through a message
# that a receiving end counting units rejects -- every time, for that bottle, for good.

EMOJI = chr(0x1F600)                       # U+1F600: one code point, two UTF-16 code units
LONE_SURROGATE = re.compile("[" + chr(0xD800) + "-" + chr(0xDFFF) + "]")


def units(text):
    """UTF-16 code units. Raises UnicodeEncodeError on a lone surrogate, which is itself a
    useful check that none got in."""
    return len(text.encode("utf-16-le")) // 2


@pytest.fixture(scope="module")
def nb():
    """The notifier as a module, for the helpers a CLI run cannot reach on its own."""
    spec = importlib.util.spec_from_file_location("notify_closed_bottles_under_test", NOTIFY_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _astral_history(recs):
    """Sixty forwarded hops between agents whose names are all emoji, and a quarantine line
    whose reason is all emoji, inserted after `create`."""
    recs.insert(1, {"at": "2026-01-01T00:00:30Z", "id": CID, "event": "corrupt",
                    "by": "system", "reason": EMOJI * 5000})
    for i in range(60):
        recs.insert(1, {"at": f"2026-01-01T00:01:{i:02d}Z", "id": CID, "event": "forward",
                        "by": EMOJI * 100, "to": EMOJI * 100})
    return recs


def _all_astral_resolve():
    recs = make_bottle(CID, "resolve", task=EMOJI * 5000, result=EMOJI * 5000, by=EMOJI * 100)
    recs[0]["to"] = EMOJI * 100
    return _astral_history(recs)


def _all_astral_cancel():
    recs = make_bottle(CID, "cancel", task=EMOJI * 5000, reason=EMOJI * 5000, by=EMOJI * 100)
    recs[0]["to"] = EMOJI * 100
    return _astral_history(recs)


def _all_astral_fail():
    recs = make_bottle(CID, "fail", task=EMOJI * 5000, reason=EMOJI * 5000, by=EMOJI * 100)
    recs[0]["to"] = EMOJI * 100
    return _astral_history(recs)


@pytest.mark.parametrize("build", [_all_astral_resolve, _all_astral_cancel, _all_astral_fail],
                         ids=["resolve", "cancel", "fail"])
def test_the_whole_message_cap_holds_in_utf16_units_for_emoji_text(notifier, build):
    """Task, result or reason, agent names and a long history are all U+1F600. The message
    that reaches `openclaw` is at most 1900 UTF-16 code units AND at most 1900 characters,
    carries no lone surrogate (a cut must not split a pair), and still announces the history
    it dropped."""
    recs = build()
    msg = _send_via_finalize(notifier, recs)

    assert units(msg) <= 1900, f"{units(msg)} UTF-16 code units ({len(msg)} characters)"
    assert len(msg) <= 1900
    assert not LONE_SURROGATE.search(msg), "a lone surrogate reached the message"
    assert msg.startswith(("\u2705", "\u274c", "\u26a0")), "the header must survive"
    assert "   Task: " in msg and "   Hops: " in msg
    assert re.search(r"\d+ more history line\(s\) omitted", msg), "no truncation marker"
    dropped = int(re.search(r"(\d+) more history line", msg).group(1))
    shown = sum(1 for l in msg.split("\n") if l.startswith("     - "))
    assert dropped + shown == len(recs), "every history line is shown or counted"
    assert shown >= 1
    # The cap is a cap, not a target: the field caps are in characters, so an emoji-only
    # message is mostly head, and what is left over is not wasted on a short history.
    assert units(msg) > 1900 - 400, f"history was dropped far below the limit: {units(msg)}"


def test_an_ordinary_message_is_exactly_what_it_was_before(notifier):
    """The unit change must not touch a message that already fit: plain ASCII ledger text,
    short history, no marker, byte for byte."""
    recs = [{"at": "2026-01-01T00:00:00Z", "id": CID, "event": "create", "by": "main",
             "to": "main", "task": "plain task"},
            {"at": "2026-01-01T00:00:01Z", "id": CID, "event": "cancel", "by": "main",
             "reason": "no longer needed"}]
    msg = _send_via_finalize(notifier, recs)

    lyra = "\u2728 LYRA (Main) [deepseek-v4-flash]"
    assert msg == "\n".join([
        f"\u274c [MIAB Bottle Cancelled] {CID}",
        "   Task: plain task",
        "   Reason: no longer needed",
        "   Hops: 2",
        "   History:",
        f"     - \U0001f4e5 created by {lyra} -> {lyra}",
        f"     - \u274c cancelled by {lyra} (no longer needed)",
    ])


# The same function, driven directly where the CLI cannot reach: exact boundaries, and the
# last-resort cut, which no ledger can trigger while the per-field caps hold.

def test_utf16_units_counts_what_a_receiver_counting_units_would(nb):
    assert nb.utf16_units("") == 0
    assert nb.utf16_units("abc") == 3
    assert nb.utf16_units("\u00e9") == 1              # BMP, non-ASCII: still one unit
    assert nb.utf16_units(EMOJI) == 2                  # outside the BMP: a surrogate pair
    assert nb.utf16_units("a" + EMOJI * 3) == 7
    for sample in ("", "plain", "caf\u00e9", EMOJI * 40, "mixed " + EMOJI + " text"):
        assert nb.utf16_units(sample) == units(sample)
        assert nb.utf16_units(sample) >= len(sample), "never less than the character count"


def test_a_message_of_exactly_1900_units_fits_and_one_unit_more_does_not(nb):
    line = EMOJI * 450                                  # 450 characters, 900 units
    fits = nb._fit_report(["h" * 98], [line, line])     # 98 + 1 + 900 + 1 + 900 = 1900 units
    assert units(fits) == 1900
    assert fits == "\n".join(["h" * 98, line, line]), "a message that fits is returned as is"

    over = nb._fit_report(["h" * 99], [line, line])     # 1901 units, though only 1001 characters
    assert units(over) <= 1900
    assert over == "\n".join(["h" * 99, line, nb._omitted_marker(1)])


def test_the_room_kept_for_the_marker_is_measured_in_units_too(nb):
    """Two of three 800-unit lines fit with the marker exactly to the limit; one unit more
    of head and only one does."""
    line = EMOJI * 400                                  # 800 units
    marker = units(nb._omitted_marker(1))
    head = 1900 - (1 + 800) * 2 - (1 + marker)          # head units that land on 1900 exactly

    two = nb._fit_report(["h" * head], [line, line, line])
    assert units(two) == 1900
    assert two == "\n".join(["h" * head, line, line, nb._omitted_marker(1)])

    one = nb._fit_report(["h" * (head + 1)], [line, line, line])
    assert one == "\n".join(["h" * (head + 1), line, nb._omitted_marker(2)])
    assert units(one) <= 1900


@pytest.mark.parametrize("ascii_prefix", [0, 1, 2, 3])
def test_the_last_resort_cut_trims_whole_code_points_until_the_message_fits(nb, ascii_prefix):
    """A head that is itself over the limit (impossible through the CLI, which is why it is
    driven here). The cut leaves the longest prefix that fits with "..." after it: whole
    code points only, so no lone surrogate, whichever way the odd unit falls."""
    head = "a" * ascii_prefix + EMOJI * 1200
    out = nb._fit_report([head], ["first", "second"])

    expected = "a" * ascii_prefix + EMOJI * ((1900 - 3 - ascii_prefix) // 2) + "..."
    assert out == expected
    assert units(out) <= 1900                          # also proves there is no lone surrogate
    assert not LONE_SURROGATE.search(out)


def test_the_last_resort_cut_still_drops_trailing_whitespace_before_the_ellipsis(nb):
    out = nb._fit_report(["A" * 1893 + " " * 4 + "B" * 100], ["x"])
    assert out == "A" * 1893 + "..."


def test_the_last_resort_cut_of_plain_text_keeps_every_unit_it_may(nb):
    """Plain ASCII over the limit: 1897 characters and "..." make exactly 1900, no fewer."""
    out = nb._fit_report(["a" * 2500], ["x"])
    assert out == "a" * 1897 + "..."
    assert units(out) == 1900
