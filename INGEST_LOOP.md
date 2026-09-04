# Ingest loop — close the four steps, then prove it with one command

Goal: **definition-of-done statement 1 becomes true.** A repo with an
existing agent goes from `git clone` to a gated candidate **without
hand-writing a node or a scenario**, proven by a test that does exactly
that and by a first-day document written from the commands that work.

Every rule of `IMPROVE_LOOP.md` and the multi-agent protocol of
`ABOVE_90_LOOP.md` apply unchanged. HARD-STOP gates bind. Read `CLAUDE.md`
first. **No increment here claims a rubric point** — adoption readiness is
not a scoring claim, and the score stays 86 until something is measured.

## What K3 measured, and why it is a tooling list rather than an adopter list

`aef adopt` + `aef migrate` do not leave a repo that can learn. Four things
are missing, each measured by removal with the cycle's own output quoted
(ADR 0139), and each makes `aef loop cycle` **exit 0 having done nothing**:

| # | Missing | The cycle says |
|---|---|---|
| 1 | the graph under `agents/` (Zone A) | `G0 rejected it: candidate touches paths outside Zone A` |
| 2 | a module-level numeric constant | `the proposer produced nothing from the available evidence` |
| 3 | a node routing to `reflect` | `no admissible failure memory: no candidate this cycle` |
| 4 | one FAILING `aef run --memory` | the same line as 3 |

Plus: a model-calling graph cannot get its first corpus, because the
cassette does not exist until something has made the call once.

**Three of the four are tool defects, not adopter work.** This loop moves
them into the tools. Where one genuinely cannot move, it gets documented at
the point an adopter hits it — not deleted from the list.

## L1 — `aef migrate` writes into Zone A (ADR 0143)

`run_migrate` hardcodes `out = root / "aef_migrated.py"` — the repo root,
the one place the loop is structurally forbidden to propose changes to —
and the report says nothing about it. Fix wave E asked for this and could
not do it (wrong file owner).

**Change:** an `--out` threaded from `aef/cli/main.py`, **defaulting to
`f"{DEFAULT_AGENT_ROOT}/migrated/graph.py"`** imported from
`aef.harness.zones`, never spelled out. Create parents. Keep the
never-overwrite rule and `--force`'s backup (ADR 0140). `report()` names
the zone of the path it wrote. Anything that referenced `aef_migrated.py`
by name — `aef doctor`'s discovery, the generated checklist, `LOOP.md` —
follows from `DEFAULT_AGENT_ROOT` too, or it is the next drift.

**Measure:** the K3 sequence with no hand-placed graph reaches `loop cycle`
without `G0 rejected it: candidate touches paths outside Zone A`.

## L2 — migrate wires the learning loop it generates (ADR 0144)

Requirement 3 exists because the generated graph has one node and no route
to reflection, so nothing ever writes failure memory, so the proposer has
no evidence and no candidate. That is mechanical, and `make_reflect_node` /
`make_consolidate_node` already exist.

**Change:** the generated `build_graph()` wires `<call site> → reflect →
consolidate → END`, exactly as `agents/summary/graph.py` does. Every
generated node's route changes from `END` to `"reflect"`. State it in the
generated docstring: this is the wiring that makes the repo *learn*, and
removing it makes the loop silently inert.

**Falsification:** if wiring reflect changes what the node returns to an
adopter's caller, or breaks the single-node graphs the current tests pin,
that is a documented trade — generate it and say what changed, or don't and
say why. Do not quietly alter the adapter's contract with the caller.

## L3 — bootstrap leaves failure memory and can record a model-calling graph (ADR 0145)

Two gaps in one command. Requirement 4 is a *failing run whose memory the
cycle can read*; `aef loop bootstrap` already runs the graph over inputs and
already knows which runs failed. And a model-calling graph cannot bootstrap
at all — K3 got `no live provider to fall through to`.

**Change:**
- `--memory <file>`: bootstrap writes reflections to a durable store, the
  same file `aef loop cycle --memory` reads, so a failing bootstrap input
  leaves admissible failure memory behind. **Never invents a failure** — it
  records what the run did (ADR 0060's rule, again).
- `--config <aef.yaml>`: build the model provider the way `aef run` does, so
  the recording pass can make the calls the cassette will later replay.
  Recording is the one pass that is *supposed* to be live; say so in the
  help, and report calls made.

**Measure:** after `bootstrap --memory M --config aef.yaml` on a repo whose
inputs include a failing one, `aef loop cycle --memory M` proposes a
candidate. Report the model calls the recording spent.

## L4 — the numeric-constant requirement, measured not assumed (ADR 0146)

Requirement 2 is a property of `RuleBasedProposer`: it changes numeric
constants and applies one structural transformation. ADR 0122 shipped an
`LLMProposer` that writes the whole file — which may not need a constant at
all. **Nobody has checked.**

**Measure:** the K3 minimum agent with its constants removed, `loop cycle
--proposer llm` versus `--proposer rule_based`. If the LLM proposer produces
a candidate where the rule-based one cannot, requirement 2 is a
rule-based-only constraint and the generated `LOOP.md` says so beside it. If
it also produces nothing, requirement 2 is real for both and stays on the
list with the reason. **Live calls: budget ≤ 8, and run the quota preflight
in `TO_90_LOOP.md` first** — if quota is unavailable, record the increment
as blocked rather than guessing.

## L5 — `bless` must archive the tree that contains the agent (ADR 0147)

K3 reproduced: `aef loop bless --agent-path aef_migrated.py` printed
`blessed aef_migrated.py as baseline v1` while archiving a Zone A tree whose
only file was `agents/README.md`. It checks `path_exists_at(ref,
agent_path)` and then archives `agents/**` — two different questions, and
the message names the first. The obligation goes green on evidence
unrelated to the agent, and G5's whole drift budget is then measured against
a baseline that never contained it.

**Change:** refuse when the agent path is not inside the archived tree,
naming both paths. L1 makes this harder to reach; it does not fix it.

## L6 — the first-day document (ADR 0148)

K4 was never written, and now it can be written from commands that work.
`AGENT_INTEGRATION.md` and the generated `CLAUDE.md` describe the parts;
nothing says *here is the sequence, here is what each step costs, here is
what does not work until you have done it*. Include what L1–L5 changed,
what still requires a person, and the failure modes named — starting with
the one that bit every raw-SDK adopter: **your function keeps its own
client, so the gates cannot replay it.**

Ship it through `aef adopt`, and add it to `tests/test_prompt_surface.py`'s
surface list so it cannot rot. It must also document `aef loop bootstrap`,
which the generated `LOOP.md` and `AGENT_INTEGRATION.md` currently never
mention at all (found by fix wave D, left for this).

## L7 — the acceptance test (ADR 0149)

One `slow` test, and it is the definition of done:

**A repo containing only a raw-SDK agent goes `adopt` → `migrate` →
`bootstrap` → `bless` → `cycle` and gets a candidate proposed and gated on
real evidence, with no hand-written node, no hand-written scenario, and no
credential.**

Extend K3's `test_an_adopted_repo_gates_a_candidate_end_to_end` by deleting
its hand-written parts one at a time as L1–L3 land. Assert against
`ledger.jsonl`, not CLI text — K3's reproduction found the previous test
asserting a line the cycle prints *before* it does anything. Keep asserting
a **rejection** verdict: a test demanding acceptance can be satisfied by
weakening G3.

Whatever still requires a person on the day this test is written is the
honest remainder, and it goes in L6's document and in the report.

## L8 — the pilot (owner action, then ADR 0150)

One real repo, owner-chosen, **not the live trading system**: adopt,
migrate, bootstrap, bless, run real work with `--record-runs`, harvest those
runs (redaction on), one `loop cycle`, read what the gates said. Everything
before this is validated against fixtures this project wrote to be passed.

## Rules this loop adds, learned the hard way tonight

- **When two increments touch a shared format, the contract needs a test
  that runs the REAL producer into the REAL consumer.** Waves C and D both
  passed, merged cleanly, and every refusal silently stopped parsing,
  because D's fixture was a hand copy of C's template whose docstring
  claimed copying it "verbatim" would catch drift. A duplicate cannot detect
  drift from the thing it duplicates.
- **A test that asserts CLI text can assert something printed before the
  work happens.** Assert the artefact — the ledger, the corpus, the file.
- **Reverting a mutation with `git checkout --` destroys uncommitted work.**
  Back up byte-for-byte and verify with `shasum`.
- Workers: `PYTHONPATH=$PWD PATH=<repo>/.venv/bin:$PATH`, pytest
  `--basetemp` **outside** the worktree and outside any dot-directory, no
  background tasks, foreground with the Bash `timeout` parameter.

## After each merge wave

Seam-hunt the diff. **Eleven for eleven** — every adversarial round in this
programme has found a defect, and the last one found twelve including two
that made shipped ADR claims false. Weight it at the joins between
`adopt`, `migrate`, `bootstrap`, `bless`, `preflight` and `cycle`, which
this loop changes all at once.

## Report

`docs/research/ingest-<date>.md`: the four steps with what each now costs an
adopter, the acceptance test's output, what still requires a person, and the
pilot as the only open item. Then stop.
