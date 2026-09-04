# Ready loop — make adoption actually work

Goal, and it is not the rubric: **an adopter with an existing agent can
reach a governed, learning, gateable setup in one sitting, and the tooling
refuses to report green when they have not.**

Every rule of `IMPROVE_LOOP.md` and the multi-agent protocol of
`ABOVE_90_LOOP.md` apply unchanged. HARD-STOP gates bind. Read `CLAUDE.md`
first. This loop may run before, after, or instead of `TO_90_LOOP.md` —
none of its increments depend on model quota.

## What was measured, 2026-09-04

`aef adopt` then `aef migrate` on a fresh repo containing one real agent
(`src/my_agent.py`, 8 lines, constructs `anthropic.Anthropic()` directly):

- adopt wrote 15 files, detected `raw_sdk` correctly, **read none of the
  code** — `aef_adapter.py` raises `NotImplementedError` by design
- migrate **did** work: 1 call site found, wrapped, `aef_migrated.py` with
  a runnable `build_graph()`
- **but the wrapper calls `run_agent(state.objective)`, and `run_agent`
  still builds its own client.**

That last line is the readiness blocker, and it is this repo's signature
defect shape: a green light for something that does not hold.

## K1 — an adopted repo's model call must be visible to the harness (ADR 0137)

**Reproduce first, RUN.** Take the adopted+migrated repo above. Show all
four of these, each as a command with its output:

1. `aef doctor` reports green.
2. The migrated node's model call does **not** go through
   `Services.model_provider` — it bypasses the policy engine, the fallback
   chain, and the harness login, so the repo still needs an API key that
   ADR 0112 exists to remove.
3. Because the call is invisible, no `RecordedCall` is captured, so the
   scenario carries no cassette and `isolated_suite`'s `on_miss="fail"`
   cannot replay it — the gates either make live calls or score it 0.
4. Nothing anywhere warns about any of this.

**Change, two parts.**

*(a) Point the existing detector at the adopter.* `tests/test_vendor_isolation.py`
already AST-scans for vendor SDK imports and has enforced constraint #3 in
this repo since Phase 0. Lift its scanner into `aef/` (it is currently
test-only — that is why it never ran for an adopter) and add a **preflight
obligation**: a module reachable from the configured graph that imports a
vendor SDK is an unmet obligation, named, with the fix in the message. Do
not silently pass a repo that will fail at gate time. Reuse the scanner —
a second list of vendor module names is ADR 0091's drift waiting to happen.

*(b) Make `aef migrate` generate the routed form when it can.* When a
wrapped function's body constructs a vendor client, the generated node
should call `services.require_model_provider().complete(...)` and the
report should say the original function is now bypassed and its retries and
backend selection are yours to re-express. When migrate cannot tell (the
client is injected, or the function does more than one thing), it must
generate the wrapper it generates today and **say which of the two it
chose and why** — the module's existing "what this file is NOT" honesty,
extended to the choice itself.

**Falsification:** if routing through the provider loses something the
adopter's own function had — retries, streaming, a backend router — then
the honest output is a documented trade, not a silent rewrite. Say so in
the ADR and generate the unrouted form with a warning instead.

## K2 — a corpus on day one (ADR 0138)

**Reproduce.** `corpus/` after adopt contains a README. `LOOP.md` says an
empty corpus makes G2 and G3 refuse — correctly. So the loop an adopter
just installed can do nothing until they hand-record scenarios one CLI
invocation at a time, and `aef loop record` needs a `--working-memory` JSON
blob per scenario to reach a failing case at all.

**Change.** `aef loop bootstrap --inputs inputs.json`: run the configured
graph once per input, record each run as a TRAIN scenario, and report which
runs failed. Rules, each of which has a precedent to honour:

- **Never writes validation or holdout.** Same rule as `harvest` (ADR
  0076-era reasoning): if the system could fill the set that gates it, the
  gate measures the system's own choices.
- **Never labels `expected`.** Only an owner can say a task *should* have
  failed (ADR 0060). Bootstrap records what happened and prints which ids
  the owner should consider marking `must_fail`.
- **Refuses to overwrite** an existing scenario id (`recorder.py`'s rule).
- **Reports the failure count**, because a corpus where everything passes
  cannot demonstrate an improvement — and says so when the count is zero.

**Measure:** on the adopted test repo, bootstrap from a handful of inputs,
then `aef loop doctor` reaches its corpus obligation green without a single
hand-written scenario.

## K3 — prove an adopted repo can gate a candidate (ADR 0139)

**Reproduce.** `tests/cli/test_adoption_sequence.py` drives a fresh repo to
five green obligations and blesses a baseline. **Nothing proves a candidate
can then be gated.** The most expensive thing an adopter is promised —
propose, judge, keep — has never been demonstrated outside this repo's own
`agents/demo` and `agents/flaky` fixtures.

**Change.** Extend the adoption sequence test end to end, in one test that
reads as the adopter's actual first day: adopt → migrate (routed, K1) →
bootstrap a corpus (K2) → bless → `aef loop cycle` → assert a candidate was
proposed, gated, and that **the gates ran with real evidence** (not "G3
refused for lack of a cohort"). Mark it `slow`; it is N+2 corpus passes.

If the cycle cannot produce a candidate on a fresh repo — the proposer needs
recorded failure memory, which needs a failing run — then that is the
finding: **document the minimum an adopter must have before the loop can
propose anything**, and put it at the top of `LOOP.md` rather than in step
five.

## K4 — the honest first-day document (ADR 0140)

`AGENT_INTEGRATION.md` and the generated `CLAUDE.md` describe the parts. No
document says: *here is the sequence, here is what each step costs you, here
is what does not work until you have done it.* Write it, from the commands
K1–K3 actually make work, with the failure modes named — including "your
existing function keeps its own client and the gates cannot replay it",
which is the one that will bite every raw-SDK adopter.

Ship it through `aef adopt` so it lands in the adopting repo, and add it to
`tests/test_prompt_surface.py`'s surface list so it cannot silently rot.

## K5 — the pilot (owner action, then ADR 0141)

The above makes adoption *work*. Only a pilot makes it *proven*. One repo,
chosen by the owner, **explicitly not the live trading system**:

1. adopt + migrate + bootstrap + bless
2. run it for real work, `--record-runs` on
3. `aef loop harvest` its actual runs into the corpus (redaction on)
4. one `aef loop cycle`, and read what the gates said

Everything before this is a scaffold validated against a toy. This is the
first contact with a real repo, and it is also the "real signal" evidence
`docs/trust/promotion-trust-case.md` has been asking for since it was
written — worth more than any remaining point on the rubric.

## Definition of done

Not a score. Four statements, each backed by a command:

1. A raw-SDK repo goes from `git clone` to a gated candidate **without
   hand-writing a node or a scenario**.
2. Every model call in an adopted repo is visible to the harness, or the
   tooling says loudly that it is not.
3. `aef doctor` and `aef loop doctor` are green **only** when those things
   are true.
4. One real repo has done it.

Items 1–3 are this loop. Item 4 is you.

## After each merge wave

Seam-hunt the diff. Eight for eight. The adoption path is the least-tested
surface in the repo — it is exercised by fixtures that this repo wrote to
be easy — so weight the hunt toward the joins between `adopt`, `migrate`,
`doctor`, `preflight` and `loop cycle`, which have never been run in
sequence against a repo nobody designed to pass.

## Report

`docs/research/ready-<date>.md`: the four definition-of-done statements,
each with the command that demonstrates it or the reason it cannot be
demonstrated yet.
