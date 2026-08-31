# ADR-001: Skill and repository boundaries for miab-broker and its ledger readers

**Status:** Accepted (Phase 1 complete) — amended 2026-08-25
**Date:** 2026-08-19
**Amended:** 2026-08-25 — layout decided in favour of the fallback (`<name>/` at the repo root,
no `skills/` level); Phase 1 items 2–5 executed and checked off; loader tripwire recorded.
**Deciders:** Albert
**Supersedes:** the implicit boundary inherited from how these skills were first written
**Related backlog items:** MQ (Q1–Q7), Q8, Q9, Q10, Q11, T20, T23, T24

---

## Context

Three programs read or write one file, `$CLAW_HOME/state/callbacks/ledger.jsonl`:

| program | lines | role | ships in |
|---|---|---|---|
| `claw-callback.py` | 1045 | **writer** — the broker CLI | `miab-broker` (published, v2.0.0) |
| `interagent_queue.py` | 371 | **reader** → renders each event into a log file | `interagent-queue` (unpublished, **not a git repo**) |
| `notify_closed_bottles.py` | 432 | **reader** → renders closed bottles, posts to chat | untracked, inside `miab-broker` |

The skill boundary today is *broker vs observer*. The question is whether to keep two skills, fold
everything into one, or draw the line somewhere else.

### What the current split has actually cost

**The coupling rule has failed or nearly failed on both occasions it was tested.** `format_event()`
returns `None` for an unrecognised event and `collect_new()` drops `None`s, so a new event type
without a renderer is *invisible* rather than an error. `corrupt` (1.2.0) rendered as nothing until
a post-implementation review caught it. `authority-override` (2.0.0) would have repeated it exactly
if the backlog hadn't carried a standing warning.

**The contract tests that now guard it are skippable.** The four cross-skill cases in
`tests/test_ledger_schema_compat.py` resolve the sibling at `../interagent-queue/scripts/` and
`pytest.skip` when it is absent. Observed directly: 2 skipped before the sibling tree was staged,
0 after. Clone `miab-broker` alone — which is exactly what a fresh checkout or CI runner does — and
the only mechanical enforcement of the coupling rule silently disappears. This is a *repository*
failure, not a skill-packaging one.

**The two readers are near-duplicates of each other.** Shared, independently maintained in both:

```
claw_home()  ledger_file()  state_file()  load_state()  save_state()
sanitize*()  AGENT_MAP  who()  collect_new()  cursor-over-ledger  main() dispatch
```

Divergent only in the sink and the rendering granularity — the observer renders per *event* to a
log file, the notifier renders per *closed bottle* to chat.

**That duplication has already caused a production incident.** Two readers meant two cursors in two
state files with two dedup models: `finalize` recorded ids in `delivered_ids` without advancing the
cursor, `process` advanced the cursor without consulting `delivered_ids`. The result was five
already-delivered bottles armed to re-post the moment cron job `0c1a123d` was repaired — the same
class of duplicate delivery as the July 2026 incident, reached by a different route. It was fixed
on 2026-08-19, but the *shape* that produced it is structural and survives the fix.

**Q9 only half-landed for the same reason.** `registry_display_names()` — reading display names
from `agent-registry.json` so there is one source of truth — exists in the observer only. The
notifier still carries its own hardcoded `AGENT_MAP` *and* a `MODEL_MAP`, free to drift exactly as
the observer's copy did.

**MQ is a tax on the boundary.** Q1–Q7 (~half a day) is security catch-up that re-derives controls
the broker already has: env-path validation, root ownership/mode, file modes, fail-closed, a test
harness, permissions frontmatter, `SECURITY.md`. It exists because a separately-publishable skill
needs its own copy of all of it. Whatever the reader count is, that cost is paid per skill.

**Q11 is this ADR, unresolved.** "Decide the split — observer stays presentation-only and consumes
`stats`, or keeps its own aggregation — before both grow half an implementation."

### What the current split has bought

**Context cost.** `miab-broker/SKILL.md` is 23 KB and every delegating agent loads it on every
broker call. `interagent-queue/SKILL.md` is 3 KB and its only readers are a cron job and an
operator. Skills are not libraries: the unit of coupling is what lands in an agent's context
window. `miab-broker-review.md` §11 already flags CLI token cost as a live concern.

**An enforceable read-only claim.** "This program never mutates the ledger" is a property that is
easy to assert, document and audit about a separate skill and much harder about a subsystem sharing
a process with the writer.

**A clean network boundary — in principle.** The broker declares `network: []`. In practice the
notifier violates this by living inside it, which is precisely why T23 is blocked.

---

## Decision

Split on **writer vs reader**, not broker vs observer. Ship **two skills in one repository**:

1. **`miab-broker`** — the writer. `claw-callback.py` + `reap-callbacks.sh`. Keeps `network: []`,
   honestly. Published to ClawHub, unchanged in scope.
2. **`miab-observer`** — the reader. Absorbs `interagent_queue.py` *and*
   `notify_closed_bottles.py` into one program with **pluggable delivery sinks** (`log`, `message`).
   One cursor, one dedup model, one identity map. Declares network honestly, because with the
   message sink it makes an outbound call.

Both live in one repo so the contract tests between them are non-optional and a known-good pair can
be tagged together.

---

## Options considered

### Option A — status quo: two skills, two repos (one of them not a repo at all)

| Dimension | Assessment |
|---|---|
| Complexity | Low today, rising — three programs, two of them near-copies |
| Cost | MQ ×1, plus permanent drift maintenance on the duplicated reader |
| Correctness | Coupling rule enforced by a skippable test and a note in a backlog |
| Publishing | Broker publishable; observer blocked on MQ; notifier homeless |

**Pros:** nothing to do. Agent context cost stays minimal.
**Cons:** every failure above persists. The notifier has no version, no changelog, no tests, and
lives in the skill whose permission declaration it contradicts. Two cursors over one file remains a
standing invitation to repeat the duplicate-delivery bug.

### Option B — one skill: fold everything into `miab-broker`

| Dimension | Assessment |
|---|---|
| Complexity | Low structurally; the coupling rule stops existing |
| Cost | Highest recurring cost, paid by every agent on every call |
| Correctness | Best — one program, no cross-process contract at all |
| Publishing | One ClawHub listing, one audit, one re-submission |

**Pros:** the coupling rule evaporates rather than being enforced — no renderer can go missing if
there is no separate renderer. MQ mostly disappears; the broker's existing controls cover it. One
version number, one changelog, one audit.
**Cons:** the decisive one is context. A merged `SKILL.md` is ~26 KB loaded by every delegating
agent on every broker call, most of it documentation for a cron-driven log renderer they will never
invoke. It also destroys the read-only guarantee: the observer's "never mutates the ledger" claim
becomes an assertion about a subsystem sharing a process with the writer. And it forces the broker
to declare network, permanently, for a feature the majority of installs won't use.

### Option C — two skills, one repo, readers merged **(recommended)**

| Dimension | Assessment |
|---|---|
| Complexity | Medium once; then lower than today |
| Cost | ~1 day, and it makes MQ *smaller* |
| Correctness | Contract tests become mandatory; one cursor, one identity map |
| Publishing | Two listings, but the reader arrives already hardened |

**Pros:** kills the duplication for real rather than papering it (Q9 lands once, not one-and-a-half
times). Gives T23's notifier a home with a version, tests and a changelog. Resolves Q11 by
construction — analytics live in the writer (T20), presentation in the reader. Contract tests move
into the repo where they cannot skip. The network declaration lands on the skill that actually
makes the call. Agent context cost is unchanged from today.
**Cons:** the reader merge is real work — two rendering granularities and two dedup models to
reconcile. Two ClawHub listings and two audits remain. The `sink` abstraction is new surface that
must not become a plugin framework.

### Option D — two skills, one repo, readers left separate

| Dimension | Assessment |
|---|---|
| Complexity | Lowest of the changes |
| Cost | ~2 hours |
| Correctness | Fixes enforcement; leaves duplication |
| Publishing | Unchanged |

**Pros:** captures the single highest-value change — non-skippable contract tests — for a fraction
of the effort. Everything else can follow later.
**Cons:** the notifier stays untracked and duplicated; Q9 stays half-landed; two cursors over one
file survive. Fixes the enforcement problem while leaving the cause.

---

## Trade-off analysis

**Context cost is what settles skill count, and it is the only argument that survives scrutiny.**
Generic modularity reasoning cuts both ways here and mostly favours merging — one program is easier
to keep correct than two that must agree. What makes skills different is that the coupling cost is
paid in tokens by every agent on every invocation, not in link-time or build-time. A 23 KB file
read constantly and a 3 KB file read by cron have no business being one artifact. That is the whole
case for Option C over Option B, and it is sufficient.

**Repo count settles correctness, and separating it from skill count is the key move.** Every
correctness failure catalogued above — skippable contract tests, duplicated identity maps, two
cursors, an untracked notifier — is a consequence of source-tree separation, not packaging
separation. Nothing about shipping two skills requires two repositories. Deciding these axes
independently is what makes it possible to keep the packaging benefit while dropping the
correctness cost.

**Merging the readers is separable from the repo move, and lower priority.** Option D is a real
fallback: if the reader merge proves harder than estimated, non-skippable contract tests in one
repo is still most of the value. Sequence accordingly.

**The remaining honest cost is duplicated hardening.** Two skills means MQ's Q1–Q4 controls exist
in two places whatever happens, because both must stay stdlib-only single-file programs that can be
copied anywhere. Merging the two readers halves the *number of places* from three to two; it does
not get to one. A shared module would, at the cost of the single-file property. Not worth it.

---

## Consequences

**Easier**

- The coupling rule becomes mechanical. Contract tests live beside both trees and fail — not skip —
  when either is missing or a renderer is absent.
- One cursor and one dedup model over the ledger. The class of bug fixed on 2026-08-19 cannot
  recur, rather than being fixed once.
- One identity map, sourced from `agent-registry.json`. Q9 finishes; the notifier's `AGENT_MAP` and
  `MODEL_MAP` go away.
- T23 unblocks: the notifier gets a version, tests, and a skill whose `network` declaration is true.
- Q7's minimum-version check becomes checkable in CI against the sibling in the same tree.
- A tagged commit means "broker X + observer Y, known good together."

**Harder**

- Two ClawHub listings, two audits, two re-submissions — unchanged from today, but now a deliberate
  standing cost rather than an accident.
- The `sink` abstraction is new surface. Two sinks, no registry, no discovery. If a third sink is
  proposed, revisit rather than generalise.
- Repo restructuring breaks any absolute path anyone has to `Skills/miab-broker/scripts/bin/`.
  Every `next_step` the CLI prints derives from `Path(__file__).resolve()` (T2), so the CLI itself
  is fine; cron entries and shell aliases are not.

**To revisit**

- **ClawHub packaging is an open question and the main risk.** The published package currently has
  `SKILL.md` at the repo root. Whether ClawHub can publish a skill from `skills/<name>/` — or wants
  one repo per skill — is unverified. Confirm before moving the broker. Fallback layout if it
  cannot: leave the broker at the repo root and nest the reader at `observer/`. Uglier, same
  correctness properties.
- **T20 vs the reader.** `stats`/`doctor` go in the writer, which owns the data. The reader
  consumes them. If the reader starts aggregating, Q11 has reopened.
- **T24 first.** `hops` is wrong in three different ways across these programs — `len(results)` in
  the broker, `len(ledger_lines)` in the notifier, absent from the envelope. Fix it *before* the
  reader merge, or the merge silently canonicalises one of the wrong definitions.

---

## Target layout

**Decided 2026-08-25: `<name>/` at the repo root — no `skills/` level.** This is the fallback the
first draft of this ADR allowed for, and it is now the decision, not a concession. The tree is
already this shape as of `34013ae` and matches what is described below.

```
miab-broker+interagent-queue/         # github.com/albzhu/miab-broker
├── README.md                         # what the pair is; which skill to install
├── miab-broker/                      # WRITER — published
│   ├── SKILL.md
│   ├── SECURITY.md
│   ├── CHANGELOG.md
│   └── scripts/
│       ├── bin/claw-callback.py
│       ├── reap-callbacks.sh
│       ├── notify_closed_bottles.py  # Phase 2: moves to the reader (T23)
│       └── notify_closed_dryrun.py   # Phase 2: retired into --dry-run
├── interagent-queue/                 # READER — absorbs both readers in Phase 2
│   ├── SKILL.md                      # declares requires: miab-broker >= 2.0.0  (Q7)
│   └── scripts/interagent_queue.py
└── tests/
    ├── conftest.py                   # resolves BOTH skill trees; no skip paths
    ├── contract/                     # a renderer per writer event type
    └── test_*.py                     # T1–T7, T12, T14, T15, T22, schema compat
```

### Why the root-level layout, not `skills/<name>/`

- **The move has already happened once, and every path reference paid for it.** `conftest.py`,
  `test_ledger_schema_compat.py`, `CHANGELOG.md`, both `SKILL.md` command examples and the cron
  job's `--command` line all encode these paths. A second migration to `skills/<name>/` costs the
  same breakage again for no functional gain.
- **`skills/` earns its keep only when non-skill top-level directories would be ambiguous.** Here
  the only other entries are `tests/` and `README.md`. The loader descends into a directory
  without a `SKILL.md` and finds nothing; there is no ambiguity to disambiguate.
- **ClawHub publishing from a subdirectory is still unverified**, and adding a second level of
  nesting can only make that harder, never easier.
- Skill identity is keyed on frontmatter `name`, not on path, so the directory level buys no
  namespacing that the frontmatter does not already provide.

### Tripwire — do not add a root `SKILL.md`

Verified against openclaw npm `2026.7.1-2` (`loadSkillEntries` / `resolveNestedSkillsRoot`):

> If `R/SKILL.md` parses with both `name` and `description`, **R itself is the one and only skill** —
> the loader returns immediately and never descends.

The repo root has no `SKILL.md`, which is the only reason both skills are reachable. A root
`SKILL.md` — added for any reason, including "so ClawHub sees something" — makes `interagent-queue`
vanish from the loader **silently**. Verify with `openclaw skills list --verbose` that exactly one
`miab-broker` and one `interagent-queue` load, and that both resolve to this repo (a stale copy
elsewhere shadows or is shadowed with no warning, because identity is keyed on frontmatter `name`).

### Naming

`interagent-queue` is unpublished, so the rename to `miab-observer` proposed in the first draft is
still free and still says what it is. It is deferred to Phase 2, where the two readers merge and the
program is rewritten anyway — renaming the directory before then would break the cron entries twice.

---

## Action items

**Phase 1 — repo (Option D; ~2 h, do this first, it stands alone)**

1. [x] ~~Confirm ClawHub can publish from `skills/<name>/`.~~ **Moot — the fallback layout is the
       decision** (see Target layout). Whether ClawHub can publish `miab-broker/` from a repo
       subdirectory is still unverified and now blocks item 12, not the layout.
2. [x] Move `interagent-queue` into the repo; move the broker under `miab-broker/`. (`34013ae`)
3. [x] Repoint `tests/`; delete every `pytest.skip` path that hides a missing sibling. All 6 are
       gone and `conftest.py` now asserts **both** skill trees exist.
4. [x] Add `tests/contract/` enumerating writer event types from the writer's AST and asserting a
       renderer for each. Verified negatively: injecting an event type with no renderer fails.
5. [x] Wire CI to run the whole suite on push (`.github/workflows/tests.yml`).

**Phase 2 — reader merge (~1 d)**

6. [ ] **T24 first** — fix `hops` before it gets canonicalised into the merged renderer.
7. [ ] Merge `notify_closed_bottles.py` into `interagent_queue.py`: one cursor, one
       `delivered_ids`, one registry-sourced identity map. Sinks `log` and `message`.
8. [ ] Fold Q1–Q4 hardening into the merged program while it is being rewritten — cheaper here
       than as a separate MQ pass.
9. [ ] Q6 (`SECURITY.md`, permissions frontmatter — declaring network for the message sink) and
       Q7 (minimum broker version + runtime check).
10. [ ] Retire `notify_closed_dryrun.py` into a `--dry-run` flag.
11. [x] Strip the hardcoded channel id; require `CLAW_CLOSED_TARGET`, fail closed when unset.
        **Pulled forward into Phase 1** — `notify_closed_bottles.py` became tracked in the combine
        commit, so the id would have entered public history on the next push. Fixed by amending
        that commit in place rather than scrubbing on top.

**Phase 3 — publish**

12. [ ] Re-submit `miab-broker` to ClawHub (it still serves **1.1.1**, the version with the S0
        primitive — this outranks everything above and should not wait for the restructure).
13. [ ] Publish `miab-observer` once MQ is closed.

**Backlog reconciliation**

14. [ ] Mark **Q11 decided** by this ADR. Fold **Q9's** remaining half and **T23** into Phase 2.
        Re-scope **MQ** to what survives the merge (Q5's harness is largely absorbed by Phase 1).

---

## Amendment — 2026-08-29

Appended, not rewritten, per house convention for ADRs.

- **Phase 3 is complete.** `miab-broker` 2.0.0 and `miab-observer` 2.0.0 were published to ClawHub on 2026-08-29 from `d31f969`. Item 12's claim that "ClawHub still serves 1.1.1" had gone stale earlier — broker 1.3.0 was published 2026-08-08. Item 13 (publish the observer) is done. Statements elsewhere in this document that the observer/reader skill "is unpublished" are superseded.
- **The rename happened.** The reader shipped as **`miab-observer`** (commit `67dc035`), preceded by an `interagent-queue` **1.3.0** deprecation release (published 2026-08-28 from `913f8b2`) directing users to the new name. State filenames were deliberately left unchanged (they key on `CLAW_HOME`, not skill name).
- **T23 is done** (`1aa4174`): the closed-bottle notifier moved into the reader skill, making the broker's `network: []` declaration true. Note the Phase 2 item 7 *program merge* (one cursor, one dedup model, sinks) remains open — the notifier moved but is not yet absorbed into `miab_observer.py`. Tracked as R2 in `ROADMAP.md`.
- **Item 14 (backlog reconciliation) is superseded** by the 2026-08-29 docs consolidation: the execution backlog, feature roadmap, and M3 scope docs were retired into `ROADMAP.md` (forward plan, T/Q numbering preserved), `STATUS.md` (current state), and `HISTORY.md` (archive).
- `main` was fast-forwarded to `d31f969` on 2026-08-29 (push to `upstream` pending review).
