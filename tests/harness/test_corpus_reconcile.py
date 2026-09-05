"""`aef loop corpus reconcile` — the documented way back from a stale manifest
(ADR 0176, F4).

THE DEFECT, reproduced on a scratch repo before anything changed. Bootstrap a
corpus of three, copy the directory, delete one scenario file, and the next
cycle refuses:

    $ aef loop cycle --repo … --corpus …/copied --no-memory
    error (CorpusShrankError): corpus shrank: 1 previously-admitted
    scenario(s) are gone: ['s-2']. A suite that can be made to pass by
    deleting the failing case is not a suite.
    exit=3

The refusal is RIGHT (ADR 0113/0138/0141: a corpus that shrinks under the loop
is the loop deleting its own evidence) and is not weakened here — it fires on
exactly the same condition. What was missing was any way back: `aef loop
--help` listed no `corpus` subcommand at all, so the only remedy was editing
`manifest.json` by hand, and the remedy people actually reach for is deleting
the manifest, which loses every id it was keeping.

The control that makes the new command safe is that the loop cannot run it.
"""

from __future__ import annotations

import ast
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.cli.main import main
from aef.harness.corpus import (
    CorpusError,
    CorpusShrankError,
    Scenario,
    Split,
    check_never_shrinks,
    load_corpus,
    load_manifest,
    reconcile_command,
    reconcile_manifest,
    save_scenario,
)
from aef.state import AEFState

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _corpus(root: Path, *ids: str, split: Split = Split.TRAIN) -> Path:
    for sid in ids:
        save_scenario(
            root,
            Scenario(
                id=sid,
                split=split,
                graph_id="demo_agent",
                graph_version="1",
                initial_state=AEFState(run_id=sid, agent_id="a", objective="o"),
                trace=(),
                recorded_at=NOW,
            ),
        )
    return root


# ---------------------------------------------------------------------------
# The refusal still fires, and now names the fix
# ---------------------------------------------------------------------------


def test_the_refusal_still_fires_on_a_deleted_scenario(tmp_path: Path) -> None:
    root = _corpus(tmp_path / "corpus", "s-1", "s-2", "s-3")
    baseline = load_manifest(root)
    (root / "train" / "s-2.json").unlink()

    with pytest.raises(CorpusShrankError) as exc:
        check_never_shrinks(load_corpus(root), baseline)

    assert "['s-2']" in str(exc.value)
    assert "not a suite" in str(exc.value), "the control's own reason must survive"


def test_the_refusal_names_the_command_that_reconciles(tmp_path: Path) -> None:
    """A control whose only remedy is hand-editing JSON is a control people
    route around by deleting the file it protects."""
    root = _corpus(tmp_path / "corpus", "s-1", "s-2")
    baseline = load_manifest(root)
    (root / "train" / "s-2.json").unlink()

    with pytest.raises(CorpusShrankError) as exc:
        check_never_shrinks(load_corpus(root), baseline)

    assert reconcile_command(root) in str(exc.value)
    assert "BY HAND" in str(exc.value)


def test_a_split_move_names_it_too(tmp_path: Path) -> None:
    root = _corpus(tmp_path / "corpus", "s-1")
    baseline = load_manifest(root)
    payload = json.loads((root / "train" / "s-1.json").read_text())
    payload["split"] = "validation"
    (root / "train" / "s-1.json").unlink()
    (root / "validation").mkdir()
    (root / "validation" / "s-1.json").write_text(json.dumps(payload))

    with pytest.raises(CorpusShrankError) as exc:
        check_never_shrinks(load_corpus(root), baseline)

    assert "changed split" in str(exc.value)
    assert reconcile_command(root) in str(exc.value)


# ---------------------------------------------------------------------------
# What the command does
# ---------------------------------------------------------------------------


def test_reconcile_prints_the_dropped_ids_and_the_next_check_passes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path / "corpus", "s-1", "s-2", "s-3")
    (root / "train" / "s-2.json").unlink()
    capsys.readouterr()

    assert main(["loop", "corpus", "reconcile", "--corpus", str(root)]) == 0
    out = capsys.readouterr().out

    assert "DROPPED  s-2 (was train) — no file on disk" in out, out
    assert "1 dropped, 0 moved, 0 added, 2 scenario(s) now recorded" in out, out
    assert "no longer admitted evidence" in out, out

    # And the guard the refusal came from now passes, on the same corpus.
    check_never_shrinks(load_corpus(root), load_manifest(root))


def test_reconcile_is_idempotent_and_says_nothing_to_do(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path / "corpus", "s-1", "s-2")
    capsys.readouterr()

    assert main(["loop", "corpus", "reconcile", "--corpus", str(root)]) == 0
    out = capsys.readouterr().out

    assert "nothing to reconcile" in out, out
    assert "DROPPED" not in out


def test_reconcile_reports_a_scenario_the_manifest_never_had(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Growth is legal and always was; the point is that it is NAMED, so the
    printed report is a complete account of what the manifest gained as well
    as what it lost."""
    root = _corpus(tmp_path / "corpus", "s-1")
    (root / "manifest.json").write_text(json.dumps({"scenarios": {}}))
    capsys.readouterr()

    assert main(["loop", "corpus", "reconcile", "--corpus", str(root)]) == 0

    assert "ADDED    s-1 (train)" in capsys.readouterr().out


def test_a_malformed_scenario_is_not_reconciled_away(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """A corrupt write must not be able to retire evidence: that is exactly
    the deletion this ledger exists to notice."""
    root = _corpus(tmp_path / "corpus", "s-1", "s-2")
    (root / "train" / "s-2.json").write_text("{not json")
    capsys.readouterr()

    assert main(["loop", "corpus", "reconcile", "--corpus", str(root)]) == 1
    assert "s-2" in capsys.readouterr().err
    assert "s-2" in load_manifest(root).ids, "the id must still be admitted"


def test_a_missing_corpus_directory_is_refused_not_created(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    missing = tmp_path / "nope"

    assert main(["loop", "corpus", "reconcile", "--corpus", str(missing)]) == 1
    assert "no corpus directory" in capsys.readouterr().err
    assert not missing.exists()


def test_the_report_can_be_taken_without_writing(tmp_path: Path) -> None:
    root = _corpus(tmp_path / "corpus", "s-1", "s-2")
    before = (root / "manifest.json").read_bytes()
    (root / "train" / "s-2.json").unlink()

    report = reconcile_manifest(root, write=False)

    assert list(report.dropped) == ["s-2"]
    assert (root / "manifest.json").read_bytes() == before, "write=False must not write"


# ---------------------------------------------------------------------------
# THE control: the loop cannot run it
# ---------------------------------------------------------------------------


def _callers_of(name: str) -> set[str]:
    """Every `aef/` function whose body mentions `name` as a call."""
    found: set[str] = set()
    for path in sorted(Path("aef").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                called = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                if called == name:
                    found.add(f"{path.as_posix()}::{node.name}")
    return found


def test_only_the_owner_command_calls_reconcile_manifest() -> None:
    """ADR 0060's shape. The manifest is the never-shrinks ledger the
    behavioural gates are measured against; a loop that can rewrite its own
    ledger between turns can retire the scenario it fails and score the result
    as an improvement. So `cycle`, `run` and the driver may not reach this.

    Verified against a planted fault: adding `reconcile_manifest(root)` inside
    `cmd_cycle` makes this test fail with that call site named.
    """
    assert _callers_of("reconcile_manifest") == {"aef/cli/loop.py::cmd_corpus_reconcile"}


def test_neither_cycle_nor_run_mentions_reconciling_at_all() -> None:
    """The belt to the above's braces: an indirect helper introduced between
    `cmd_cycle` and `reconcile_manifest` would slip past a one-hop call scan,
    so the name is also banned from the two handlers' source outright."""
    source = Path("aef/cli/loop.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"cmd_cycle", "cmd_run"}:
            body = ast.get_source_segment(source, node) or ""
            assert "reconcile" not in body, f"{node.name} must not reconcile anything"


def test_the_loop_driver_never_writes_a_manifest_wholesale() -> None:
    """`save_manifest` is legitimate — `_record_in_manifest` unions one id in
    as it is admitted. What must not exist is a driver-side rewrite."""
    assert not (
        _callers_of("save_manifest")
        - {
            "aef/harness/corpus.py::_record_in_manifest",
            "aef/harness/corpus.py::reconcile_manifest",
        }
    )


# ---------------------------------------------------------------------------
# End to end: copy, delete, refuse, reconcile, proceed
# ---------------------------------------------------------------------------


def test_the_whole_sequence_at_the_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    (repo / "agents" / "demo").mkdir(parents=True)
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 3\n")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@t"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    root = _corpus(tmp_path / "corpus", "s-1", "s-2", "s-3")
    (root / "train" / "s-2.json").unlink()

    def cycle() -> int:
        return main(
            [
                "loop",
                "cycle",
                "--repo",
                str(repo),
                "--state",
                str(tmp_path / "state"),
                "--workdir",
                str(tmp_path / "work"),
                "--corpus",
                str(root),
                "--no-memory",
            ]
        )

    capsys.readouterr()
    assert cycle() == 3, "the refusal must still fire"
    assert "corpus shrank" in capsys.readouterr().err

    assert main(["loop", "corpus", "reconcile", "--corpus", str(root)]) == 0
    assert "DROPPED  s-2" in capsys.readouterr().out

    assert cycle() == 0, "and the next cycle proceeds"


def test_a_reconcile_that_cannot_read_the_corpus_raises_a_corpus_error(tmp_path: Path) -> None:
    root = _corpus(tmp_path / "corpus", "s-1")
    (root / "train" / "s-1.json").write_text("{}")

    with pytest.raises(CorpusError):
        reconcile_manifest(root)
