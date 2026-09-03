"""`aef loop score` — the task metric read directly (ADR 0113)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aef.cli.main import main
from aef.harness.checks import TaskCheck
from aef.harness.corpus import CorpusManifest, Scenario, Split, save_manifest, save_scenario
from aef.kernel import GraphExecutor
from aef.services.runtime import agent_services
from aef.state import AEFState

ENTRYPOINT = "agents.demo.graph:build_graph"


def _corpus(tmp_path: Path) -> Path:
    """Two train scenarios with checks the demo passes, one validation scenario
    whose check the demo cannot pass (it writes quality 0.0 and errors), one
    unchecked."""
    from agents.demo.graph import build_graph

    graph = build_graph()
    root = tmp_path / "corpus"
    manifest = CorpusManifest()

    def add(sid: str, split: Split, wm: dict[str, int], checks: tuple[TaskCheck, ...]) -> None:
        state = AEFState(run_id=sid, agent_id="a", objective=f"task {sid}", working_memory=wm)
        recorded = GraphExecutor(graph.compile(), agent_services()).run(state, record_trace=True)
        assert recorded.trace is not None
        scenario = Scenario(
            id=sid,
            split=split,
            graph_id="demo_agent",
            graph_version="0.1.0",
            initial_state=state,
            trace=recorded.trace,
            recorded_at=datetime(2026, 9, 3, tzinfo=UTC),
            checks=checks,
        )
        save_scenario(root, scenario)
        manifest.ids[sid] = split

    quality_ok = (TaskCheck(path="scores.quality", op="equals", value=1.0),)
    add("easy-a", Split.TRAIN, {"difficulty": 1, "quality_needed": 1}, quality_ok)
    add("easy-b", Split.TRAIN, {"difficulty": 2, "quality_needed": 2}, quality_ok)
    add("hard", Split.VALIDATION, {"difficulty": 9, "quality_needed": 9}, quality_ok)
    add("unchecked", Split.VALIDATION, {"difficulty": 1, "quality_needed": 1}, ())
    save_manifest(root, manifest)
    return root


def test_score_prints_one_scalar_per_split_with_statistics(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    code = main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--json", "--repeat", "3"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    train, val = report["train"], report["validation"]
    assert (train["n"], train["with_checks"]) == (2, 2)
    assert train["mean"] == 1.0
    assert val["per_scenario"] == {"hard": 0.0, "unchecked": 1.0}
    assert val["mean"] == 0.5
    assert "ci95" in val and "stdev" in val
    # Deterministic graph, pinned clock: three identical runs, zero spread.
    assert train["repeat_mean_spread"] == 0.0
    assert report["repeat"] == 3


def test_score_refuses_the_holdout_without_the_flag(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    code = main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--splits", "holdout"])
    assert code != 0
    assert "holdout" in capsys.readouterr().err


def test_score_human_output_lists_each_scenario(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root)]) == 0
    out = capsys.readouterr().out
    assert "task metric" in out
    assert "0.0000  hard" in out
    assert "1.0000  easy-a" in out
