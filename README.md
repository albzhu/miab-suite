# miab-broker + miab-observer

Two OpenClaw skills that share one file and therefore share one repository.

`ledger.jsonl` — an append-only record of every inter-agent callback — is written by one program and
read by another. When those two lived in separate trees, the only mechanical enforcement of their
shared schema was a test that skipped itself whenever the other tree was absent, which is exactly
what a fresh clone or a CI runner looks like. Combining them makes the contract testable
unconditionally. See [`ADR-001`](#design-decisions) for the full reasoning.

| directory | skill | role |
|---|---|---|
| [`miab-broker/`](miab-broker/) | `miab-broker` | **writer** — the broker CLI. Creates, forwards, returns, resolves and reaps callbacks; appends every event to the ledger. |
| [`miab-observer/`](miab-observer/) | `miab-observer` | **reader** — renders each ledger event into a human-readable log, and can post closed-bottle summaries to a chat channel. |
| [`tests/`](tests/) | — | one suite, resolving both trees. No skip paths. |
| [`docs/`](docs/) | — | status, roadmap, history and the design record ([ADR-001](#design-decisions)). |

Install either skill on its own; `miab-observer` requires `miab-broker` to be present, since it
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
drives it as a subprocess, the way it is actually used. Python 3.10 or newer; CI runs 3.10 and 3.12.
Run everything from the repository root.

```bash
python3 -m pytest -q                          # the whole suite
python3 -m pytest -q --strict-markers -rs     # exactly what CI runs: unknown markers fail, skips are listed
```

If `pytest` is missing: on macOS, `pip install pytest` is usually refused (Homebrew's Python is
"externally managed") or installs somewhere `python3` cannot see. Use a throwaway environment
instead; nothing is written inside the repository.

```bash
uvx pytest -q                                 # if you have uv

python3 -m venv /tmp/miab-venv                # otherwise, a disposable venv
/tmp/miab-venv/bin/python -m pip install -q pytest
/tmp/miab-venv/bin/python -m pytest -q
```

The venv is enough because pytest is the suite's only third-party dependency, and
`tests/conftest.py` runs each CLI with the interpreter that runs the tests (`sys.executable`).

A healthy run reports **0 skipped and exactly 1 xfailed**:

- A skip means a skill tree is missing — a broken checkout, not a condition to tolerate.
  `tests/conftest.py` asserts both trees exist at import time, and CI fails on any skip.
- The xfail is `tests/test_xfail_t11_concurrency.py`, a standing reproduction of a known race
  between concurrent writes to one bottle (T11 in [`docs/ROADMAP.md`](docs/ROADMAP.md)). If it
  ever reports **XPASS**, something changed underneath it; find out what before carrying on.

Running part of the suite:

```bash
python3 -m pytest -q tests/test_t25_doctor.py     # one file
python3 -m pytest -q tests/test_notifier_*.py     # the chat notifier (the observer's message sink)
python3 -m pytest -q tests/contract/              # the writer/reader contract, below
python3 -m pytest -q -k session_key               # tests whose names match an expression
python3 -m pytest -q --lf -x                      # re-run the last failures, stop at the first
```

No test touches real state: each one runs against a throwaway `CLAW_HOME`, and the notifier tests
put a fake `openclaw` first and alone on `PATH`, so nothing can be posted to a chat channel.

If a `_to_delete/` directory exists at the root (see [Housekeeping](#housekeeping)), add
`--ignore=_to_delete` until it is cleared, or collection fails.

### `tests/contract/`

The directory that justifies the repository. It parses the writer's source for every event type it
can append to the ledger, and asserts the reader has a renderer for each.

This guards a failure that is silent rather than loud: `format_event()` returns `None` for an event
type it does not recognise, and `collect_new()` drops `None`s. A new event type without a renderer
does not error — it simply never appears in the log. That shipped once (`corrupt`, 1.2.0) and came
within a standing backlog note of shipping again (`authority-override`, 2.0.0). The list is derived
from the writer's AST, never hand-kept, because a hand-kept list fails in precisely the case it
exists to catch.

## Common commands

Run from the repository root, after setting:

```bash
CB=miab-broker/scripts/bin/claw-callback.py
OBS=miab-observer/scripts
```

These act on **live state**: both skills default to `CLAW_HOME=~/.openclaw`. The last column says
which commands change anything. To try those safely, point `CLAW_HOME` at a scratch directory
with mode `0700` (the broker refuses a root that anyone else can access). Every command exits
non-zero on failure.

When the gateway runs these skills it gives them the environment declared in `openclaw.json`
(`skills.entries.<skill>.env`), not your shell's. When you run one by hand, export the same values
first — at least `CLAW_HOME`, and `CLAW_CLOSED_TARGET` for the notifier — or you will be looking
at different files from the ones your agents use. Each skill's `SKILL.md` lists its variables.

### Broker — is delegation set up right, and what is in flight?

| command | what it does | changes anything? |
|---|---|---|
| `python3 $CB -h`, `python3 $CB <subcommand> -h` | every subcommand, and each one's flags | no |
| `python3 $CB doctor` | reconciles `openclaw.json`, the agent registry and the ledger; prints the minimum `register` commands, and any config fragment, needed for delegation to work. Exits 1 on a `blocking` or `routing` finding | no — never writes `openclaw.json` |
| `python3 $CB doctor --json` | the same findings, for a script or an agent | no |
| `python3 $CB doctor --commands-only` | only the `register` lines, in the order they must run | no |
| `python3 $CB doctor --ignore <name>` | leaves a retired agent's name, still in the ledger, out of the `unknown-agent` check | no |
| `python3 $CB doctor --config <path>` | checks a config other than `$CLAW_HOME/openclaw.json` (or set `OPENCLAW_CONFIG`) | no |
| `python3 $CB list` / `list --json` | bottles in flight: id, status, holder, stack depth, task | moves an unreadable envelope to `archive/corrupt/` |
| `python3 $CB show --id <cid>` | one bottle: holder, stack, resume context | no |
| `python3 $CB wake --id <cid>` | the dispatch message, and the exact call that wakes the holder | no |
| `python3 $CB sweep --older-than <minutes>` | pending bottles older than that; add `--fail` to fail them | rotates the ledger once it passes 10,000 lines; `--fail` fails and purges bottles |
| `miab-broker/scripts/reap-callbacks.sh --dry-run` | what the reaper would fail (`--max-age 6h` for another threshold) | appends to `callback-reaper.log`, and rotates like `sweep` |

Do not schedule the reaper on its 120-minute default yet: about a quarter of real returns take
longer than that (T16 in [`docs/ROADMAP.md`](docs/ROADMAP.md)).

### Observer — the log sink and the chat notifier

| command | what it does | changes anything? |
|---|---|---|
| `python3 $OBS/miab_observer.py status` | log sink: on or off, cursor, log and ledger paths | no |
| `python3 $OBS/miab_observer.py peek` | what `process` would write to the log | no |
| `python3 $OBS/miab_observer.py process` | appends new ledger events to the log | yes: the log and its cursor |
| `python3 $OBS/miab_observer.py on` / `off` | turns the log sink on or off | yes |
| `python3 $OBS/notify_closed_dryrun.py [<cid>] [--json]` | renders closed-bottle messages exactly as they would be posted | no: reads no state, never runs `openclaw` |
| `python3 $OBS/notify_closed_bottles.py status` | notifier: on or off, cursor, target, state-file path | no |
| `python3 $OBS/notify_closed_bottles.py peek` | what `process` would post | no |
| `python3 $OBS/notify_closed_bottles.py render <cid>` | one bottle's message | no |
| `python3 $OBS/notify_closed_bottles.py process` | posts newly closed bottles to `CLAW_CLOSED_TARGET`; this is what cron runs | **yes: posts to chat** |
| `python3 $OBS/notify_closed_bottles.py finalize <cid>` | posts one bottle now, once | **yes: posts to chat** |
| `python3 $OBS/notify_closed_bottles.py on` / `off` | turns delivery on or off | yes |

`process`, `finalize` and `on` need `CLAW_CLOSED_TARGET` — a target that
`openclaw message send --target` accepts, such as `channel:<id>`. Without it they exit 1 and
send nothing. What else makes the notifier exit 1, and how to recover from each case:
[`miab-observer/SKILL.md`](miab-observer/SKILL.md) §3a.

### Checking an install

```bash
openclaw skills list --verbose   # exactly one miab-broker and one miab-observer, both from this repo
python3 $CB doctor               # after any change to openclaw.json or to the agent roster
```

### Releasing

Each skill is published on its own, and ClawHub owns the version number, so `SKILL.md` frontmatter
never carries one. Publish from `git archive`, never from the working tree: the archive holds
exactly the committed skill directory, without `tests/`, `docs/`, caches or untracked files.

```bash
python3 -m pytest -q --strict-markers -rs                # green on the commit you will publish
REL=$(git rev-parse HEAD)
rm -rf /tmp/miab-pub && mkdir -p /tmp/miab-pub
git archive "$REL" <skill> | tar -x -C /tmp/miab-pub     # <skill> is miab-broker or miab-observer
ls -R /tmp/miab-pub/<skill>                              # SKILL.md at the top, no tests/ or docs/
(cd /tmp/miab-pub && clawhub skill publish <skill> --version <X.Y.Z>)   # --version is required
```

Then confirm the new version on the ClawHub listing. Push `main` and the release tag by name
(`git push upstream main`, `git push upstream <tag>`), never with `--all` or `--mirror`, which
would also publish local-only branches and refs.

### Housekeeping

Tools that cannot delete files, such as some sandboxed agent shells, park what they would have
removed in `_to_delete/` at the root (gitignored) and in `.git/_to_delete/`, and can leave git's
temporary object files behind. Clear all of it from a normal shell:

```bash
rm -rf _to_delete .git/_to_delete && git prune
```

## Layout note — do not add a root `SKILL.md`

Skills are discovered by walking directories for `SKILL.md`. If the **repository root** has one that
parses, the loader treats the root as the one and only skill and never descends — `miab-observer`
would silently stop loading. The root deliberately has no `SKILL.md`, and this README is not one.

Verify with `openclaw skills list --verbose` that exactly one `miab-broker` and one
`miab-observer` load, and that both resolve to this repository. Skill identity is keyed on the
frontmatter `name`, not the path, so a stale copy elsewhere shadows or is shadowed with no warning.

## Design decisions

The project's working documents are in [`docs/`](docs/):

- [`ADR-001-skill-and-repo-boundaries.md`](docs/ADR-001-skill-and-repo-boundaries.md) — why there
  are two skills in one repo, why the readers merge in Phase 2, and why the layout is `<name>/` at
  the root rather than `skills/<name>/`.
- [`ROADMAP.md`](docs/ROADMAP.md) — what is planned, in order, and the standing decisions.
- [`STATUS.md`](docs/STATUS.md) — the current state and the open punchlist.
- [`HISTORY.md`](docs/HISTORY.md) — what shipped, and the reasoning behind it.
