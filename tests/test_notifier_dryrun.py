"""notify_closed_dryrun.py: show what the notifier would send, without sending it.

Until 2.0.1 it loaded the notifier through `importlib.util.spec_from_file_location` +
`spec.loader.exec_module()`, which ClawHub's static scan reports as critical "dynamic
code execution". It is now an ordinary import of the sibling module — which also makes
"the dry run shows exactly what the notifier posts" true by construction rather than by
convention, and these tests keep it true.
"""
import json
import re

import pytest

from conftest import DRYRUN_SCRIPT, NOTIFY_SCRIPT, IQ_ROOT, make_bottle

HOSTILE = "@everyone <@&123> <#123> [x](http://y)"
A = "cb-20260101000000-aaa001"
B = "cb-20260101000100-bbb002"
C = "cb-20260101000200-ccc003"

LEDGER = (make_bottle(A, "resolve", t0=0, task=HOSTILE, result=HOSTILE)
          + make_bottle(B, "cancel", t0=10, task="plain", reason=HOSTILE)
          + make_bottle(C, "fail", t0=20, task="x" * 2000, reason="y" * 10_000))


def test_dryrun_output_is_exactly_what_the_notifier_would_send(notifier):
    """Test 9. Same ledger, three routes to the same text: the dry-run script, `render`,
    and the message the fake `openclaw` actually received from a real delivery."""
    notifier.write_ledger(LEDGER)

    dry = notifier.run("--json", script=DRYRUN_SCRIPT)
    assert dry.returncode == 0, dry.stderr
    assert notifier.calls() == [], "the dry run must never invoke openclaw"
    bottles = json.loads(dry.stdout)["bottles"]
    assert [b["id"] for b in bottles] == [A, B, C]
    dry_messages = [b["message"] for b in bottles]

    for cid in (A, B, C):
        assert notifier.run("finalize", cid).returncode == 0
    sent = notifier.messages()
    assert sent == dry_messages

    for cid, msg in zip((A, B, C), sent):
        rendered = notifier.run("render", cid)
        assert rendered.returncode == 0, rendered.stderr
        assert rendered.stdout == msg + "\n"
        single = notifier.run(cid, script=DRYRUN_SCRIPT)
        assert msg in single.stdout

    # ... and it is the neutralised text, not just the same text.
    for msg in sent:
        assert "@everyone" not in msg and "<@" not in msg and "<#" not in msg
        assert "](" not in msg
        assert len(msg) <= 1900


def test_dryrun_plain_output_and_unknown_bottle(notifier):
    notifier.write_ledger(make_bottle(A, "resolve"))
    r = notifier.run(script=DRYRUN_SCRIPT)
    assert r.returncode == 0, r.stderr
    assert f"Bottle: {A}" in r.stdout
    assert "[dry-run] 1 finished bottle(s) rendered. Nothing sent." in r.stdout

    r = notifier.run("cb-no-such-bottle", script=DRYRUN_SCRIPT)
    assert r.returncode == 0, r.stderr
    assert "(no message)" in r.stdout
    assert notifier.calls() == []


def test_dryrun_survives_odd_ledger_lines(notifier):
    """It shares the notifier's record parsing, so a line that is not an object, or an
    end-state record with a non-string id or event, is skipped rather than fatal."""
    lines = ["[1, 2]", "5", "not json {",
             json.dumps({"id": 7, "event": "resolve"}),
             json.dumps({"id": B, "event": ["resolve"]})]
    lines += [json.dumps(r) for r in make_bottle(A, "resolve")]
    notifier.write_ledger_lines(lines)

    r = notifier.run("--json", script=DRYRUN_SCRIPT)
    assert r.returncode == 0, r.stderr
    assert [b["id"] for b in json.loads(r.stdout)["bottles"]] == [A]


@pytest.mark.parametrize("script", [NOTIFY_SCRIPT, DRYRUN_SCRIPT], ids=lambda p: p.name)
def test_observer_scripts_contain_no_dynamic_code_execution(script):
    """The scanner finding was `exec_module` in the dry-run script; pin the whole class."""
    src = script.read_text(encoding="utf-8")
    assert "exec_module" not in src
    assert not re.search(r"\beval\s*\(", src)
    assert not re.search(r"\bexec\s*\(", src)


def test_dryrun_imports_the_notifier_the_ordinary_way():
    src = DRYRUN_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^import notify_closed_bottles\b", src, re.M)
    assert "spec_from_file_location" not in src
    assert (IQ_ROOT / "scripts" / "notify_closed_bottles.py").exists()
