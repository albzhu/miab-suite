"""Extract the set of ledger event types the writer can emit, from its source.

The list is derived by parsing claw-callback.py, never hand-kept. A hand-kept
list is exactly what failed twice: `corrupt` shipped in 1.2.0 with no renderer,
and `authority-override` in 2.0.0 came within a backlog note of repeating it.
An unrendered event type is invisible rather than broken -- format_event()
returns None for anything it does not recognise and collect_new() drops Nones --
so the failure mode is silence, which no ordinary test catches.
"""
import ast
from pathlib import Path

LEDGER_WRITER = "ledger_append"


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _event_literal(node: ast.Dict) -> str | None:
    """The string value of this dict literal's "event" key, if it has one."""
    for key, value in zip(node.keys, node.values):
        if isinstance(key, ast.Constant) and key.value == "event":
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def writer_event_types(source: Path) -> set[str]:
    """Every event type passed to ledger_append() as a dict literal."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node.func) != LEDGER_WRITER or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Dict):
            event = _event_literal(first)
            if event is not None:
                found.add(event)
    return found


def all_event_dict_literals(source: Path) -> set[str]:
    """Every dict literal anywhere in the source carrying a literal "event" key.

    Superset of writer_event_types(). Used to detect the one way the extractor
    above can go blind: a record built into a variable, or passed through a
    helper, instead of inlined at the ledger_append() call site.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            event = _event_literal(node)
            if event is not None:
                found.add(event)
    return found
