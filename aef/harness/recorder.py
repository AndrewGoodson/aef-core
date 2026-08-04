"""Promoting a real run into a corpus scenario.

The corpus is what every behavioural gate stands on, so how entries get into
it matters as much as what the gates do with them.

**Scenarios are recorded, never hand-authored.** A hand-written scenario
encodes what someone *believed* the graph does; a recorded one encodes what
it did. The difference shows up exactly when they diverge, which is the case
the corpus exists to catch.

**The holdout is not writable by default.** `train` is the proposer's
evidence, `validation` is what gates score against, and `holdout` is the
owner's only independent read. A recorder that filled the holdout as
casually as it fills train would destroy that independence without anyone
noticing — so writing there needs an explicit, separate act.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aef.harness.corpus import Scenario, Split, load_corpus, save_scenario
from aef.kernel import GraphExecutor, Services
from aef.kernel.graph import Graph
from aef.state import AEFState


class RecorderError(RuntimeError):
    pass


class HoldoutWriteRefused(RecorderError):
    """Writing to the owner's holdout without explicit consent. Its own type
    because it is not a validation failure — it is a request to spend the
    only independent evidence the owner has."""


@dataclass(frozen=True)
class RecordedScenario:
    scenario: Scenario
    path: Path


def record_run(
    graph: Graph,
    initial_state: AEFState,
    services: Services,
    *,
    scenario_id: str,
    split: Split = Split.TRAIN,
    recorded_at: datetime,
    notes: str = "",
    allow_holdout: bool = False,
) -> Scenario:
    """Execute `graph` and capture the run as a `Scenario`.

    The clock is whatever `services` supplies; the recorded `Context.now`
    values become the scenario's pinned clock (ADR 0048), so a re-execution
    observes exactly what the recording did.
    """
    if split is Split.HOLDOUT and not allow_holdout:
        raise HoldoutWriteRefused(
            "refusing to write to the holdout split. It is the owner's only independent "
            "read of whether the loop is improving anything, and a recorder that fills it "
            "as casually as it fills train destroys that independence silently. Pass "
            "allow_holdout=True to spend it deliberately."
        )

    result = GraphExecutor(graph.compile(), services).run(initial_state, record_trace=True)
    if result.trace is None:  # pragma: no cover - record_trace=True guarantees it
        raise RecorderError("execution produced no trace to record")
    if not result.trace:
        raise RecorderError(
            f"scenario {scenario_id!r} executed no nodes; an empty trace pins nothing and "
            f"would pass every gate vacuously"
        )

    return Scenario(
        id=scenario_id,
        split=split,
        graph_id=graph.id,
        graph_version=graph.version,
        initial_state=initial_state,
        trace=result.trace,
        recorded_at=recorded_at,
        notes=notes,
    )


def record_to_corpus(
    root: Path,
    graph: Graph,
    initial_state: AEFState,
    services: Services,
    *,
    scenario_id: str,
    split: Split = Split.TRAIN,
    recorded_at: datetime,
    notes: str = "",
    allow_holdout: bool = False,
) -> RecordedScenario:
    """Record and persist, refusing to overwrite an existing scenario.

    Silently replacing a scenario is how a corpus stops binding: the entry
    that used to fail is gone, and `check_never_shrinks` cannot tell, because
    the id is still there.
    """
    existing = {s.id for s in load_corpus(root).scenarios} if root.is_dir() else set()
    if scenario_id in existing:
        raise RecorderError(
            f"scenario {scenario_id!r} already exists. Overwriting it would replace the "
            f"behaviour the corpus recorded with the behaviour it has now, which is "
            f"precisely the regression a corpus exists to catch. Pick a new id."
        )

    scenario = record_run(
        graph,
        initial_state,
        services,
        scenario_id=scenario_id,
        split=split,
        recorded_at=recorded_at,
        notes=notes,
        allow_holdout=allow_holdout,
    )
    return RecordedScenario(scenario=scenario, path=save_scenario(root, scenario))
