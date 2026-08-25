"""Writer/reader event-type contract.

Standing invariant (ADR-001, and the reason these two skills now share a repo):
every event type `claw-callback.py` can append to ledger.jsonl must have a
renderer in `interagent_queue.py`. `format_event()` returns None for an
unrecognised type and `collect_new()` drops Nones, so a missing renderer is
*silent* -- the event simply never appears in the log or the Discord-facing
feed. That has bitten twice already, which is why the writer's list is derived
from its own source here rather than kept by hand.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import CB_SCRIPT, IQ_SCRIPT

from .event_types import all_event_dict_literals, writer_event_types

# Types known to exist as of 2.0.0. This is a floor, not the source of truth:
# it only proves the AST extraction still finds things. New types must NOT be
# added here -- they are discovered from the writer automatically, and the
# coverage test below is what makes them mandatory.
KNOWN_MINIMUM = {
    "create", "forward", "return", "resolve",
    "cancel", "fail", "authority-override", "corrupt",
}


def _render(claw_home, records):
    """Append records to a scratch ledger and return the reader's rendered output."""
    callbacks = claw_home / "state" / "callbacks"
    callbacks.mkdir(parents=True, exist_ok=True)
    ledger = callbacks / "ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    env = os.environ.copy()
    env["CLAW_HOME"] = str(claw_home)
    env["LYRA_WORKSPACE"] = str(claw_home / "workspace")
    result = subprocess.run([sys.executable, str(IQ_SCRIPT), "peek"],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["messages"]


def test_extraction_still_finds_the_writers_events():
    """Guard the extractor itself. If a refactor breaks the AST walk this test
    fails loudly, instead of the coverage test below silently passing on an
    empty set."""
    found = writer_event_types(CB_SCRIPT)
    missing = KNOWN_MINIMUM - found
    assert not missing, (
        f"AST extraction no longer finds {sorted(missing)} in {CB_SCRIPT.name}. "
        "Either those event types were removed (a ledger schema break -- see "
        "test_ledger_schema_compat.py) or the extractor needs updating.")


def test_extractor_sees_every_event_dict_in_the_writer():
    """The one way writer_event_types() can go blind: a ledger record built into
    a variable, or handed to a helper, instead of inlined at the ledger_append()
    call site. Every literal "event" dict in the writer must be reachable."""
    inline = writer_event_types(CB_SCRIPT)
    everywhere = all_event_dict_literals(CB_SCRIPT)
    unreachable = everywhere - inline
    assert not unreachable, (
        f"event type(s) {sorted(unreachable)} appear in a dict literal that "
        f"writer_event_types() cannot see. Either inline the record at the "
        f"ledger_append() call site, or teach event_types.py the new pattern -- "
        f"otherwise the coverage test below stops covering them.")


@pytest.mark.parametrize("event", sorted(writer_event_types(CB_SCRIPT)))
def test_every_writer_event_type_has_a_renderer(event, claw_home):
    """The contract. A writer event type with no renderer in the reader renders
    as nothing at all, silently -- this is the test that makes that a failure."""
    cid = "cb-20260101000000-" + f"{abs(hash(event)) % 0xffffff:06x}"
    rendered = _render(claw_home, [{
        "at": "2026-01-01T00:00:00Z",
        "id": cid,
        "event": event,
        "by": "system",
    }])
    joined = "\n".join(rendered)
    assert cid[:14] in joined, (
        f"event type {event!r} was dropped instead of rendered. "
        f"format_event() in {IQ_SCRIPT.name} returns None for it, and "
        f"collect_new() drops Nones -- so it is invisible, not broken. "
        f"Add a renderer branch for {event!r}.")


def test_unknown_event_type_is_still_dropped(claw_home):
    """The failure mode this suite exists to catch, asserted directly: an event
    type the reader does not know renders as nothing. This is what makes the
    parametrized test above meaningful rather than vacuous."""
    rendered = _render(claw_home, [{
        "at": "2026-01-01T00:00:00Z",
        "id": "cb-20260101000000-ffffff",
        "event": "definitely-not-a-real-event-type",
        "by": "system",
    }])
    assert "cb-20260101000" not in "\n".join(rendered)
