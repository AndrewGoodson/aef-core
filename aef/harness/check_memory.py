"""A failed owner check becomes failure memory (ADR 0174).

The wire this closes was found from both ends on the same night.

**From M4's end** (ADR 0157): a prompt-file agent that *answers* cannot
produce failure memory. `make_reflect_node` writes `kind="failure"` iff
`failure_signals(state)` is non-empty, and that reads `state.errors` and
`state.tool_results`. An owner **check** is the task metric (ADR 0113),
evaluated by the harness *after* the run, and it never touches either. So a
bootstrapped run that failed its owner's check wrote
`kind="success", verbal_feedback="no failure signals: 0 error(s) recorded…"`
and `aef loop cycle` said `no admissible failure memory` forever.

**From S1's end** (ADR 0155): zero knowledge entries formed in any of the four
ACE arms, because every record on the summary split was a `success` whose
signature is `"success:" + objective` — six distinct objectives, six unique
signatures, and ADR 0110's two-run threshold unreachable by construction.
Two of those six runs *failed an owner check*.

One producer answers both. It evaluates the owner's checks against the final
state and, when any fail, runs the **real** `Critic`/`Judge` over that state
with the check failures supplied as evidence, and writes one
`kind="failure"` `MemoryRecord`.

## Three rules it is built to

**It never invents a failure** (ADR 0060, ADR 0145). The check is the owner's,
written before the run; the observed value is the run's. This module decides
neither. It is the same distinction `BootstrapInput` already draws: `expected`
is a judgement about what a run turned out to do and is refused, while
`checks` are "a specification of the task written before the run". Evaluating
a specification the owner wrote against output the run produced is recording
what happened.

**It never writes when the run also errored.** A run that raised already has a
failure record from its own reflect node, and `score_scenario` itself ignores
the check fraction when `final_state.errors` is non-empty — a second record
built from checks the scorer disregarded would be evidence of something
nobody measured.

**It never copies the check's expected value.** ACE's method and teaching to
the test are the same operation (ADR 0157), and the one thing that separates
them is whether the lesson carries the answer. `RuleBasedPromptProposer` pastes
an entry's `latest_feedback` verbatim into the agent's persona, so a literal
`contains 'VERDICT:'` in this record's `verbal_feedback` is a target string
appended to the prompt. The rendering below names the state path, the
operator in prose, and the **observed** value — never `check.value`. What it
still leaks is stated in ADR 0174 and is not nothing.

## The signature, and why it drops the expected value too

`default_signature` keys a check-derived failure on `check:<path>:<op>` per
failed check — the check's identity **without** its value. Two consequences,
both deliberate:

- The same field failing the same kind of check on two different inputs
  **recurs**, which is what makes ADR 0110's two-run rule reachable at all.
  Keyed with the value's hash instead, the summary split produces two
  singleton groups and still zero entries (measured, ADR 0174).
- Nothing that reaches a prompt as a provenance marker (`<!-- aef
  sig=… -->`, `render_retrieved_context`'s `[label]`) carries the answer.

The cost is that two required-substring failures on one field merge into one
lesson. That is one behaviour — "this field keeps omitting a required term" —
not a catch-all across unrelated failures, which is the thing
`consolidate.py` warns against.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aef.harness.checks import TaskCheck, evaluate_checks, resolve
from aef.reasoning.nodes import retrieved_signatures
from aef.reasoning.reflection import Critic, Judge
from aef.services.memory.base import MemoryRecord, MemoryStore
from aef.state import AEFState, StateDelta

# The "node" credited with OBSERVING the failure. `make_reflect_node` records
# `ctx.node_id` here; the observer of a check is the harness's scorer, which is
# not a graph node, and naming a real node would attribute the observation to
# code that never ran. `failing_nodes` stays empty for the same reason: no node
# raised, so there is nothing to attribute (ADR 0096's field means the node
# that CAUSED the error).
CHECK_OBSERVER_NODE_ID = "task_checks"

# Key prefix for one failed check inside a signature. Read by
# `consolidate.default_signature`, which joins the keys with ">" exactly as it
# joins failing node ids.
CHECK_KEY_PREFIX = "check:"

# How much of the OBSERVED value each line quotes. The critic excerpts every
# quoted signal at 160 characters (`MAX_EXCERPT_CHARS`), so a longer quote here
# would simply be cut there, mid-word, and push the prose that explains it out
# of the record.
MAX_OBSERVED_CHARS = 60

# The prose each operator gets, with the expected value REMOVED. Present as a
# table rather than an f-string chain so that adding an op to `checks.OPS`
# without deciding how it reads here fails loudly in `_describe_failure`
# instead of silently rendering the value.
_OP_PROSE: dict[str, str] = {
    "contains": "does not contain a required substring the owner declared",
    "equals": "does not equal the value the owner declared",
    "regex": "does not match the pattern the owner declared",
    "exists": "was never recorded",
    "max_words": "is longer than the owner's maximum",
    "min_words": "is shorter than the owner's minimum",
}


def check_key(check: TaskCheck) -> str:
    """One failed check's identity, value excluded.

    A path containing `>` would be split by `consolidate._failure_nodes` when
    it parses a signature for the helpful/harmful tally. Grouping is exact
    string equality and is unaffected; only the tally could mis-parse, and a
    state path with `>` in it is not something the checks in this repo
    produce. Recorded rather than guarded, because a guard here would have to
    rewrite the path and two paths would then collide.
    """
    return f"{CHECK_KEY_PREFIX}{check.path}:{check.op}"


def _observed(final_state: AEFState, check: TaskCheck) -> str:
    found, value = resolve(final_state, check.path)
    if not found:
        return "<missing>"
    text = value if isinstance(value, str) else repr(value)
    words = f"{len(text.split())} words, " if isinstance(value, str) else ""
    body = " ".join(text.split())
    if len(body) > MAX_OBSERVED_CHARS:
        body = body[: MAX_OBSERVED_CHARS - 1] + "…"
    return f"{words}{len(text)} chars: {body!r}"


def _describe_failure(final_state: AEFState, check: TaskCheck) -> str:
    """One line of evidence about one failed check, with the owner's expected
    value left out. `check.value` is never read here — asserted by a test that
    plants an unusual literal in a check and greps the whole record for it."""
    prose = _OP_PROSE.get(check.op)
    if prose is None:  # pragma: no cover - `OPS` and `_OP_PROSE` are pinned equal by a test
        prose = "did not satisfy the owner's check"
    if check.op == "exists":
        return f"check failed: {check.path} {prose}"
    return f"check failed: {check.path} {prose}; observed {_observed(final_state, check)}"


def check_failure_record(
    *,
    checks: Sequence[TaskCheck],
    final_state: AEFState,
    critic: Critic,
    judge: Judge,
    run_id: str,
    agent_id: str,
    created_at: datetime,
    graph_version: str = "",
    tags: tuple[str, ...] = (),
) -> MemoryRecord | None:
    """The `kind="failure"` record for a run whose owner checks did not hold,
    or `None` when there is nothing to record.

    `None` when: no checks were declared, every check held, or the run
    recorded an error of its own — see the module docstring for why the third
    is not an omission.

    **The derived state.** The `Critic` reads `state.errors`, so the check
    failures are supplied by applying a `StateDelta` carrying them to a LOCAL
    copy of the final state. That copy never leaves this function: the
    scenario, the trace, `classify`, `score_scenario` and the corpus all see
    the state the run actually produced. Injecting the failures into the real
    run state instead would make the run look like it raised — `classify`
    would report it failed for the wrong reason, and `score_scenario` would
    stop counting the check fraction *because* the checks failed, which is a
    metric that changes when you measure it (ADR 0174 rejects that design and
    says so).

    `Critique.grounded_in` therefore indexes the derived evidence, not the
    recorded state; the same lines sit at the same indices in the record's
    `check_failures`, so every citation still resolves to something a reader
    can see.
    """
    if not checks:
        return None
    if final_state.errors:
        return None
    report = evaluate_checks(checks, final_state)
    if not report.failures:
        return None

    lines = [_describe_failure(final_state, check) for check in report.failed]
    keys: list[str] = []
    for check in report.failed:
        key = check_key(check)
        if key not in keys:
            keys.append(key)

    derived = StateDelta(errors=[{"error": line} for line in lines]).apply(final_state)
    critique = critic.critique(derived)
    judgment = judge.judge(derived)

    return MemoryRecord(
        kind="failure",
        content={
            "verbal_feedback": critique.verbal_feedback,
            "grounded_in": list(critique.grounded_in),
            "score": judgment.score,
            "rubric": dict(judgment.rubric),
            "rationale": judgment.rationale,
            "node_id": CHECK_OBSERVER_NODE_ID,
            # No node raised. `failing_nodes` names the node that CAUSED an
            # error and there is none; `failed_checks` is what this failure is
            # keyed on instead (see `consolidate.default_signature`).
            "failing_nodes": [],
            "failed_checks": keys,
            "check_failures": lines,
            "checks_passed": report.passed,
            "checks_total": report.total,
            "retrieved_signatures": retrieved_signatures(final_state),
            "graph_version": graph_version,
            "objective": final_state.objective,
        },
        run_id=run_id,
        agent_id=agent_id,
        tags=tags,
        created_at=created_at,
    )


def write_check_failure_record(
    *,
    memory: MemoryStore,
    checks: Sequence[TaskCheck],
    final_state: AEFState,
    critic: Critic,
    judge: Judge,
    run_id: str,
    agent_id: str,
    created_at: datetime,
    graph_version: str = "",
    tags: tuple[str, ...] = (),
) -> MemoryRecord | None:
    """`check_failure_record`, written to `memory`. Returns the record, or
    `None` when there was none to write."""
    record = check_failure_record(
        checks=checks,
        final_state=final_state,
        critic=critic,
        judge=judge,
        run_id=run_id,
        agent_id=agent_id,
        created_at=created_at,
        graph_version=graph_version,
        tags=tags,
    )
    if record is not None:
        memory.write(record)
    return record
