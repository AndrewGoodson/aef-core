"""A corpus on day one — running the graph once per owner-supplied input.

`aef adopt` writes a `corpus/README.md` and nothing else, and G2/G3 correctly
refuse an empty corpus. So the loop an adopter has just installed can do
nothing until they hand-record scenarios one `aef loop record` invocation at
a time, each needing its own `--working-memory` JSON blob to reach a failing
case at all (ADR 0074 added that flag; it did not make it cheap). This module
turns a file of inputs into a train corpus in one command.

Four rules, each with a precedent this module is not allowed to break.

**Always TRAIN. Never validation, never holdout, and no flag to override.**
Verbatim from `harvest.py`: if the system could fill the set that gates it,
the gate would measure the system's own choices. `recorder.py` refuses the
holdout without explicit consent; here, as in harvest, there is not even a
way to ask.

**Never labels `expected`.** Only an owner can say a task *should* have
failed (ADR 0060), and a `must_fail` label the system invented is a tripwire
the system set for itself. Bootstrap records what happened and prints which
ids the owner should consider marking. An `expected` key in the inputs file
is REFUSED rather than ignored — an owner who wrote a claim and had it
silently dropped would believe the corpus carries it.

**Refuses to overwrite an existing scenario id**, and refuses the whole
invocation before running anything, so a batch that collides halfway through
does not leave a half-written corpus behind. The check and its wording are
`recorder.refuse_existing_ids`, shared rather than restated — a second copy
of a rule is ADR 0091's drift waiting to happen.

**Reports the failure count, and says so when it is zero.** A corpus where
everything already passes cannot demonstrate an improvement: every gate that
reads it has nothing to hold a candidate to. That is a finding about the
inputs, not a success, and it is printed as one.

**Fresh services per input.** The gates re-execute each scenario in
isolation, with its own `InMemoryMemoryStore` (`harvest._reexecution_services`).
A bootstrap that shared one store across inputs would record traces whose
later runs depended on what earlier ones remembered — scenarios that cannot
reproduce alone, which is the one thing a corpus must never contain.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aef.harness.checks import CheckError, TaskCheck
from aef.harness.corpus import Expected, Scenario, Split
from aef.harness.outcome import classify
from aef.harness.recorder import RecorderError, record_to_corpus, refuse_existing_ids
from aef.kernel import Services
from aef.kernel.graph import Graph
from aef.state import AEFState

DEFAULT_PREFIX = "bootstrap"

# Everything an input may say. Anything else is a typo or a claim this
# command does not honour, and both are worth an error rather than a shrug.
INPUT_KEYS = frozenset({"id", "objective", "working_memory", "notes", "checks", "budget_ms"})

# Keys that name a rule bootstrap enforces. Refused by name, with the
# command that DOES accept them, so an owner never believes a claim landed.
REFUSED_KEYS: dict[str, str] = {
    "expected": (
        "only an owner can say a task should have failed (ADR 0060), and bootstrap has just "
        "run the task, so any label it wrote would be one the system set for itself. Record "
        "the tripwire deliberately instead: aef loop record <module> --expected must_fail"
    ),
    "split": (
        "bootstrap writes the train split only, as harvest does: if the system could fill "
        "the set that gates it, the gate would measure the system's own choices. Use "
        "aef loop record --split validation for a scenario the gates score against"
    ),
}


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootstrapInput:
    """One task to run. `checks` and `budget_ms` are the OWNER's claims about
    the answer (ADR 0113) and are carried through verbatim — unlike
    `expected`, they are a specification of the task written before the run,
    not a judgement about what the run turned out to do, so nothing about
    reading them here lets the system grade itself."""

    id: str
    objective: str
    working_memory: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    checks: tuple[TaskCheck, ...] = ()
    budget_ms: float | None = None


def _parse_input(raw: Any, index: int, prefix: str) -> BootstrapInput:
    where = f"input {index}"
    if not isinstance(raw, dict):
        raise BootstrapError(f"{where}: each input must be a JSON object, got {type(raw).__name__}")
    for key in raw:
        if key in REFUSED_KEYS:
            raise BootstrapError(f"{where}: {key!r} is not accepted — {REFUSED_KEYS[key]}")
    unknown = sorted(set(raw) - INPUT_KEYS)
    if unknown:
        raise BootstrapError(
            f"{where}: unknown key(s) {unknown}; an input may set {sorted(INPUT_KEYS)}"
        )

    objective = raw.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise BootstrapError(f"{where}: 'objective' is required and must be a non-empty string")

    scenario_id = raw.get("id", f"{prefix}-{index}")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise BootstrapError(f"{where}: 'id' must be a non-empty string")

    working_memory = raw.get("working_memory", {})
    if not isinstance(working_memory, dict):
        raise BootstrapError(
            f"{where}: 'working_memory' must be a JSON object — it seeds "
            f"AEFState.working_memory, which is how an input reaches the agent's FAILING "
            f"cases (ADR 0074)"
        )

    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise BootstrapError(f"{where}: 'notes' must be a string")

    raw_checks = raw.get("checks", [])
    if not isinstance(raw_checks, list):
        raise BootstrapError(f"{where}: 'checks' must be a JSON list of check objects")
    checks: list[TaskCheck] = []
    for entry in raw_checks:
        if not isinstance(entry, dict):
            raise BootstrapError(f"{where}: a check must be a JSON object")
        try:
            checks.append(TaskCheck.from_payload(entry))
        except CheckError as exc:
            # Malformed here, before anything runs: a check that loaded wrong
            # would score its scenario 0 forever and read as a regression.
            raise BootstrapError(f"{where}: {exc}") from exc

    budget_ms = raw.get("budget_ms")
    if budget_ms is not None and not isinstance(budget_ms, int | float):
        raise BootstrapError(f"{where}: 'budget_ms' must be a number of milliseconds")

    return BootstrapInput(
        id=scenario_id,
        objective=objective,
        working_memory=dict(working_memory),
        notes=notes,
        checks=tuple(checks),
        budget_ms=None if budget_ms is None else float(budget_ms),
    )


def load_inputs(path: Path, *, prefix: str = DEFAULT_PREFIX) -> tuple[BootstrapInput, ...]:
    """Parse an inputs file.

    Shape, documented here and in `--inputs`' help: a JSON list of objects,
    or an object with an `inputs` list. Each object needs `objective` and may
    set `id` (default `<prefix>-<n>`), `working_memory`, `notes`, `checks`
    and `budget_ms`. Objective plus working memory is the minimum because
    that is exactly what `AEFState` needs to reach a task at all, failing
    ones included.
    """
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise BootstrapError(f"no inputs file at {path}") from exc
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"{path}: not valid JSON: {exc}") from exc

    if isinstance(payload, dict):
        payload = payload.get("inputs")
    if not isinstance(payload, list):
        raise BootstrapError(
            f"{path}: expected a JSON list of inputs, or an object with an 'inputs' list"
        )
    if not payload:
        raise BootstrapError(
            f"{path}: no inputs. Bootstrap runs the graph once per input; with none there "
            f"is nothing to record and the corpus stays empty."
        )
    return tuple(_parse_input(raw, i + 1, prefix) for i, raw in enumerate(payload))


@dataclass(frozen=True)
class BootstrapOutcome:
    """What one bootstrap did. `failed` is the number the whole command
    exists to report."""

    recorded: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    # (id, message) for an input whose run raised before producing a trace.
    # Nothing is recorded for those: a scenario with no trace pins nothing.
    errored: tuple[tuple[str, str], ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        out: list[str] = [
            f"recorded {len(self.recorded)} scenario(s) in the {Split.TRAIN.value} split"
        ]
        for sid in self.recorded:
            out.append(f"  {'FAILED' if sid in self.failed else 'passed'}  {sid}")
        for sid, message in self.errored:
            out.append(f"  ERRORED (nothing recorded)  {sid}: {message}")
        total = len(self.recorded)
        if not total:
            # Never the zero-failure sentence: "everything passed" and
            # "nothing ran" are different facts, and printing the first for
            # the second is exactly the green-light-for-nothing shape this
            # repo keeps finding. The adoptee case that produced it: every
            # input raised because the migrated node builds its own vendor
            # client and there is no credential (the K1 defect).
            out.append(
                "NOTHING was recorded and the corpus is unchanged. Every input raised "
                "before producing a trace, so there is no run to pin; a scenario with an "
                "empty trace pins nothing and would pass every gate vacuously."
            )
        elif self.failed:
            out.append(f"{len(self.failed)} of {total} recorded run(s) FAILED.")
            out.append(
                "  Bootstrap labels nothing: only an owner can say a task SHOULD have "
                "failed (ADR 0060). Consider marking one of these a tripwire — "
                f"{', '.join(self.failed)}"
            )
        else:
            out.append(
                f"0 of {total} recorded run(s) failed. A corpus where everything passes "
                f"cannot demonstrate an improvement — every gate reading it has nothing to "
                f"hold a candidate to. Add inputs whose working_memory drives the agent "
                f"into its failing cases."
            )
        return tuple(out)

    def tripwire_commands(
        self, module: str, corpus: str, inputs: Sequence[BootstrapInput]
    ) -> tuple[str, ...]:
        """The `aef loop record` line the owner runs to turn one failed input
        into a tripwire, with its objective and working memory filled in.

        Generated, never executed. The label is the owner's act (ADR 0060),
        and `record_run` still refuses `must_fail` on a task the agent
        completes — so this is a suggestion the recorder itself checks.
        """
        by_id = {i.id: i for i in inputs}
        commands: list[str] = []
        for sid in self.failed:
            item = by_id.get(sid)
            if item is None:  # pragma: no cover - failed ids come from inputs
                continue
            commands.append(
                f"aef loop record {module} --corpus {corpus} "
                f"--scenario-id {sid}-tripwire --objective {json.dumps(item.objective)} "
                f"--working-memory {json.dumps(json.dumps(item.working_memory))} "
                f"--split validation --expected must_fail"
            )
        return tuple(commands)


def _final_state(scenario: Scenario) -> AEFState:
    state = scenario.initial_state
    for record in scenario.trace:
        state = record.delta.apply(state)
    return state


def bootstrap(
    corpus_root: Path,
    graph: Graph,
    services_factory: Callable[[], Services],
    *,
    inputs: Sequence[BootstrapInput],
    now: datetime,
    agent_id: str,
) -> BootstrapOutcome:
    """Run `graph` once per input and record each run as a TRAIN scenario.

    `services_factory` is called once PER INPUT — see the module docstring.
    There is no `split` parameter and no `expected` parameter, deliberately:
    both are rules, and a rule with a keyword argument is a default.
    """
    # Whole-batch, before anything runs. A collision found halfway through
    # would leave scenarios written for the inputs before it, which is a
    # corpus nobody asked for and a command nobody can safely re-run.
    refuse_existing_ids(corpus_root, [i.id for i in inputs])

    recorded: list[str] = []
    failed: list[str] = []
    errored: list[tuple[str, str]] = []

    for item in inputs:
        state = AEFState(
            run_id=item.id,
            agent_id=agent_id,
            objective=item.objective,
            working_memory=dict(item.working_memory),
        )
        try:
            result = record_to_corpus(
                corpus_root,
                graph,
                state,
                services_factory(),
                scenario_id=item.id,
                split=Split.TRAIN,
                recorded_at=now,
                notes=item.notes or "bootstrapped from an owner-supplied input",
                # Never a claim. Explicit rather than defaulted so a change
                # to it is a change to this line, which a test can catch.
                expected=Expected.UNSPECIFIED,
                checks=item.checks,
                budget_ms=item.budget_ms,
            )
        except RecorderError:
            # The overwrite refusal and the empty-trace refusal are both
            # conditions the whole invocation should stop on, not per-input
            # noise to summarise.
            raise
        except Exception as exc:  # noqa: BLE001 - a node that raised is reported, not recorded
            errored.append((item.id, f"{type(exc).__name__}: {exc}"))
            continue

        recorded.append(result.scenario.id)
        # The same `classify` the gates read and `record_run` checks
        # MUST_FAIL against, so "failed" here means what it means to G2.
        outcome = classify(_final_state(result.scenario), result.scenario.trace, terminated=True)
        if not outcome.passed:
            failed.append(result.scenario.id)

    return BootstrapOutcome(recorded=tuple(recorded), failed=tuple(failed), errored=tuple(errored))
