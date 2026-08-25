# miab-broker + interagent-queue

Two OpenClaw skills that share one file and therefore share one repository.

`ledger.jsonl` — an append-only record of every inter-agent callback — is written by one program and
read by another. When those two lived in separate trees, the only mechanical enforcement of their
shared schema was a test that skipped itself whenever the other tree was absent, which is exactly
what a fresh clone or a CI runner looks like. Combining them makes the contract testable
unconditionally. See [`ADR-001`](#design-decisions) for the full reasoning.

| directory | skill | role |
|---|---|---|
| [`miab-broker/`](miab-broker/) | `miab-broker` | **writer** — the broker CLI. Creates, forwards, returns, resolves and reaps callbacks; appends every event to the ledger. |
| [`interagent-queue/`](interagent-queue/) | `interagent-queue` | **reader** — renders each ledger event into a human-readable log. |
| [`tests/`](tests/) | — | one suite, resolving both trees. No skip paths. |

Install either skill on its own; `interagent-queue` requires `miab-broker` to be present, since it
has nothing to read otherwise.

## What a bottle is

An agent that needs work done by another agent does not block on it. It writes a "message in a
bottle" — a callback frame naming who to wake when the result comes back — pushes it onto a LIFO
stack, and yields its turn. The broker moves the bottle down the delegation chain
(`register → create → forward → return → resolve`) and unwinds it back up, waking each agent at the
point it left off. The alternative is a poll loop that burns a turn per check.

Full protocol, security model and command reference: [`miab-broker/SKILL.md`](miab-broker/SKILL.md).

## Running the tests

Standard library plus `pytest`. Nothing else, on purpose — the broker is stdlib-only and the suite
drives it as a subprocess, the way it is actually used.

```bash
pip install pytest
pytest
```

Expect **0 skipped**. A skip here means a tree is missing, which is a broken checkout rather than a
condition to tolerate; `tests/conftest.py` asserts both skill trees exist at import time so the
failure is loud.

### `tests/contract/`

The directory that justifies the repository. It parses the writer's source for every event type it
can append to the ledger, and asserts the reader has a renderer for each.

This guards a failure that is silent rather than loud: `format_event()` returns `None` for an event
type it does not recognise, and `collect_new()` drops `None`s. A new event type without a renderer
does not error — it simply never appears in the log. That shipped once (`corrupt`, 1.2.0) and came
within a standing backlog note of shipping again (`authority-override`, 2.0.0). The list is derived
from the writer's AST, never hand-kept, because a hand-kept list fails in precisely the case it
exists to catch.

## Layout note — do not add a root `SKILL.md`

Skills are discovered by walking directories for `SKILL.md`. If the **repository root** has one that
parses, the loader treats the root as the one and only skill and never descends — `interagent-queue`
would silently stop loading. The root deliberately has no `SKILL.md`, and this README is not one.

Verify with `openclaw skills list --verbose` that exactly one `miab-broker` and one
`interagent-queue` load, and that both resolve to this repository. Skill identity is keyed on the
frontmatter `name`, not the path, so a stale copy elsewhere shadows or is shadowed with no warning.

## Design decisions

`ADR-001 — Skill and repository boundaries` records why there are two skills in one repo, why the
readers merge in Phase 2, and why the layout is `<name>/` at the root rather than `skills/<name>/`.
It is kept with the project's other design documents rather than in this repository, which is public.
