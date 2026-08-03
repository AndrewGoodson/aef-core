"""`aef eval` — score a checkpointed run with `RuleBasedEvaluator`."""

from __future__ import annotations

from pathlib import Path

from aef.kernel import FileDurabilityBackend
from aef.services.eval.base import EvaluationRecord
from aef.services.eval.rule_based import RuleBasedEvaluator


def eval_run(checkpoints_dir: Path, run_id: str) -> EvaluationRecord:
    backend = FileDurabilityBackend(checkpoints_dir)
    state = backend.load_latest(run_id)
    if state is None:
        raise ValueError(f"no checkpoints found for run_id={run_id!r} under {checkpoints_dir}")
    return RuleBasedEvaluator().evaluate(state)
