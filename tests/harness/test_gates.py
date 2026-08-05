"""Gates G0, G1, G4, and the pipeline that orders them.

Every gate here ships with its **known-bad** case: a gate that cannot reject
is not a gate. The pipeline's ordering property is asserted directly, since
G4 running after G2 would let a proposal edit its own tests before they run.
"""

import subprocess
from pathlib import Path

import pytest

from aef.harness.candidate import inspect_candidate
from aef.harness.gates.base import (
    CANONICAL_ORDER,
    Gate,
    GateContext,
    GateOutcome,
    GateResult,
    run_pipeline,
)
from aef.harness.gates.g0_static_safety import G0StaticSafety, scan_source
from aef.harness.gates.g1_builds import G1Builds
from aef.harness.gates.g4_separation import G4SeparationOfPowers, scan_metadata
from aef.harness.git import GitRepo
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
from aef.harness.trust import TrustBoundaryError
from aef.harness.workspace import build_candidate_workspace

SAFE_AGENT = (
    "from dataclasses import dataclass\n\n\n@dataclass\nclass Planner:\n    depth: int = 3\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "base")
    _git(root, "config", "user.email", "harness@test")
    _git(root, "config", "user.name", "harness")
    (root / "agents").mkdir()
    (root / "aef" / "harness").mkdir(parents=True)
    (root / "agents" / "planner.py").write_text(SAFE_AGENT)
    (root / "aef" / "harness" / "gate.py").write_text("MARKER = 'base'\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def _candidate(repo: GitRepo, files: dict[str, str], *, message: str = "cand") -> None:
    _git(repo.root, "checkout", "-qb", "cand")
    for path, content in files.items():
        target = repo.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", message)


def _ctx(repo: GitRepo, tmp_path: Path, **limits: int) -> GateContext:
    return GateContext(
        repo=repo,
        base_ref="base",
        head_ref="cand",
        verdict=inspect_candidate(repo, "base", "cand"),
        workdir=tmp_path / "work",
        sandbox_policy=SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED, timeout_s=60),
        limits=dict(limits),
    )


# --------------------------------------------------------------------------
# G0 — static safety
# --------------------------------------------------------------------------


def test_g0_passes_an_ordinary_zone_a_change(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": SAFE_AGENT.replace("depth: int = 3", "depth: int = 4")})
    assert G0StaticSafety().run(_ctx(repo, tmp_path)).passed


def test_g0_rejects_a_zone_c_edit(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"pyproject.toml": "[project]\n"})
    result = G0StaticSafety().run(_ctx(repo, tmp_path))
    assert not result.passed
    assert "Zone A" in result.reason


def test_g0_flags_a_zone_b_edit_as_a_security_event(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"aef/harness/gate.py": "MARKER = 'subverted'\n"})
    result = G0StaticSafety().run(_ctx(repo, tmp_path))
    assert not result.passed
    assert result.security_event


def test_g0_rejects_a_diff_over_the_line_budget(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/big.py": "".join(f"X{i} = {i}\n" for i in range(500))})
    result = G0StaticSafety().run(_ctx(repo, tmp_path))
    assert not result.passed
    assert "size budget" in result.reason


def test_g0_rejects_a_diff_over_the_file_budget(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {f"agents/m{i}.py": "X = 1\n" for i in range(5)})
    result = G0StaticSafety().run(_ctx(repo, tmp_path))
    assert not result.passed
    assert "changed files exceeds" in " ".join(result.evidence)


def test_the_size_budget_is_configurable_per_run(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {f"agents/m{i}.py": "X = 1\n" for i in range(5)})
    assert G0StaticSafety().run(_ctx(repo, tmp_path, max_changed_files=10)).passed


# --- the import allowlist (deny-by-default) --------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\n",
        "import socket\n",
        "import ctypes\n",
        "import importlib\n",
        "import pickle\n",
        "import os\n",
        "from subprocess import run\n",
        "import anthropic\n",  # vendor isolation, constraint #3
        "import openai\n",
        "from neo4j import GraphDatabase\n",
    ],
)
def test_an_import_off_the_allowlist_is_rejected(source: str) -> None:
    findings = scan_source("agents/x.py", source)
    assert len(findings) == 1
    assert "allowlist" in findings[0].problem


@pytest.mark.parametrize(
    "source",
    [
        "import json\n",
        "from dataclasses import dataclass\n",
        "from aef.kernel import Node\n",
        "import aef.state\n",
        "from typing import Any\n",
        "from . import sibling\n",  # relative, stays inside Zone A
    ],
)
def test_an_allowlisted_import_passes(source: str) -> None:
    assert scan_source("agents/x.py", source) == ()


@pytest.mark.parametrize(
    "source",
    [
        "eval('1+1')\n",
        "exec('x=1')\n",
        "compile('x', 'f', 'exec')\n",
        "__import__('os')\n",
    ],
)
def test_arbitrary_execution_is_rejected(source: str) -> None:
    findings = scan_source("agents/x.py", source)
    assert findings
    assert "arbitrary execution" in findings[0].problem


def test_reaching_interpreter_internals_is_rejected() -> None:
    findings = scan_source("agents/x.py", "def f():\n    pass\nf.__globals__['x'] = 1\n")
    assert findings
    assert "interpreter internals" in findings[0].problem


def test_a_syntax_error_is_reported_not_raised() -> None:
    findings = scan_source("agents/x.py", "def broken(\n")
    assert len(findings) == 1
    assert "syntax error" in findings[0].problem


def test_g0_scans_the_file_as_of_the_head_ref(repo: GitRepo, tmp_path: Path) -> None:
    # Not the working tree, which may hold uncommitted edits outside the
    # candidate.
    _candidate(repo, {"agents/planner.py": "import subprocess\n"})
    (repo.root / "agents" / "planner.py").write_text(SAFE_AGENT)  # uncommitted "fix"
    assert not G0StaticSafety().run(_ctx(repo, tmp_path)).passed


def test_g0_ignores_deletions_and_non_python(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/notes.md": "import subprocess is fine in prose\n"})
    assert G0StaticSafety().run(_ctx(repo, tmp_path)).passed


# --------------------------------------------------------------------------
# G4 — owner-only safety metadata
# --------------------------------------------------------------------------


def test_g4_passes_ordinary_agent_code(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": SAFE_AGENT + "\nVERSION = 2\n"})
    assert G4SeparationOfPowers().run(_ctx(repo, tmp_path)).passed


def test_deterministic_true_with_side_effects_is_rejected() -> None:
    # ReplayEngine re-executes deterministic nodes, so this repeats the I/O
    # on every replay (ADR 0046).
    source = (
        "n = Node(id='x', version='1', fn=f, deterministic=True, "
        "side_effects=SideEffect.EXTERNAL_CALL, idempotency_key_fn=lambda s: s.run_id)\n"
    )
    findings = scan_metadata("agents/x.py", source)
    assert any(f.field == "deterministic" for f in findings)


def test_deterministic_true_on_a_pure_node_is_fine() -> None:
    assert (
        scan_metadata("agents/x.py", "n = Node(id='x', version='1', fn=f, deterministic=True)\n")
        == ()
    )


def test_an_agent_declared_fallback_is_rejected() -> None:
    source = "n = Node(id='x', version='1', fn=f, deterministic=False, fallback_node_id='h')\n"
    findings = scan_metadata("agents/x.py", source)
    assert any(f.field == "fallback_node_id" for f in findings)


def test_a_constant_idempotency_key_is_rejected() -> None:
    source = (
        "n = Node(id='x', version='1', fn=f, deterministic=False, "
        "side_effects=SideEffect.IO, idempotency_key_fn=lambda s: 'fixed')\n"
    )
    findings = scan_metadata("agents/x.py", source)
    assert any(f.field == "idempotency_key_fn" for f in findings)


def test_a_state_derived_idempotency_key_is_fine() -> None:
    source = (
        "n = Node(id='x', version='1', fn=f, deterministic=False, "
        "side_effects=SideEffect.IO, idempotency_key_fn=lambda s: s.run_id)\n"
    )
    assert scan_metadata("agents/x.py", source) == ()


@pytest.mark.parametrize("flag", ["requires_human_approval", "requires_deterministic_fallback"])
def test_clearing_an_edge_control_flag_is_rejected(flag: str) -> None:
    findings = scan_metadata("agents/x.py", f"e = Edge(from_node='a', to_node='b', {flag}=False)\n")
    assert any(f.field == flag for f in findings)


def test_setting_an_edge_control_flag_on_is_fine() -> None:
    source = "e = Edge(from_node='a', to_node='b', requires_human_approval=True)\n"
    assert scan_metadata("agents/x.py", source) == ()


def test_g4_reports_a_metadata_violation_as_a_security_event(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(
        repo,
        {
            "agents/planner.py": (
                "e = Edge(from_node='a', to_node='b', requires_human_approval=False)\n"
            )
        },
    )
    result = G4SeparationOfPowers().run(_ctx(repo, tmp_path))
    assert not result.passed
    assert result.security_event


# --------------------------------------------------------------------------
# The candidate workspace
# --------------------------------------------------------------------------


def test_the_workspace_is_base_plus_zone_a_overlay(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "NEW = 1\n"})
    diff = inspect_candidate(repo, "base", "cand").diff
    dest = build_candidate_workspace(repo, diff, tmp_path / "ws")

    assert (dest / "agents" / "planner.py").read_text() == "NEW = 1\n"
    assert (dest / "aef" / "harness" / "gate.py").read_text() == "MARKER = 'base'\n"


def test_the_workspace_uses_the_base_harness_even_when_the_branch_changed_it(
    repo: GitRepo, tmp_path: Path
) -> None:
    # Defence in depth for ADR 0047: even constructing a runnable tree, the
    # branch's harness has no route in.
    _candidate(
        repo,
        {"agents/planner.py": "NEW = 1\n", "aef/harness/gate.py": "MARKER = 'subverted'\n"},
    )
    diff = inspect_candidate(repo, "base", "cand").diff
    with pytest.raises(TrustBoundaryError, match="Zone B"):
        build_candidate_workspace(repo, diff, tmp_path / "ws")


def test_a_deletion_is_applied_to_the_workspace(repo: GitRepo, tmp_path: Path) -> None:
    _git(repo.root, "checkout", "-qb", "cand")
    (repo.root / "agents" / "planner.py").unlink()
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "remove")

    diff = inspect_candidate(repo, "base", "cand").diff
    dest = build_candidate_workspace(repo, diff, tmp_path / "ws")
    assert not (dest / "agents" / "planner.py").exists()


# --------------------------------------------------------------------------
# G1 — builds
# --------------------------------------------------------------------------


def test_g1_passes_when_the_build_command_succeeds(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    gate = G1Builds(commands=(("python", "-c", "import agents.planner"),))
    assert gate.run(_ctx(repo, tmp_path)).passed


def test_g1_rejects_code_that_does_not_import(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "raise RuntimeError('broken')\n"})
    gate = G1Builds(commands=(("python", "-c", "import agents.planner"),))
    result = gate.run(_ctx(repo, tmp_path))
    assert not result.passed
    assert "exit" in result.reason


def test_g1_runs_against_the_merged_workspace_not_the_branch(repo: GitRepo, tmp_path: Path) -> None:
    # The command asserts the base-ref harness marker is present alongside
    # the candidate's change — i.e. it really is the post-merge tree, not a
    # checkout of either side. Read from disk rather than imported: the
    # installed `aef` package would shadow the workspace's copy and the test
    # would prove nothing about which tree the command ran in.
    _candidate(repo, {"agents/planner.py": "VALUE = 2\n"})
    gate = G1Builds(
        commands=(
            (
                "python",
                "-c",
                "assert open('agents/planner.py').read().strip() == 'VALUE = 2'; "
                "assert open('aef/harness/gate.py').read().strip() == \"MARKER = 'base'\"",
            ),
        )
    )
    assert gate.run(_ctx(repo, tmp_path)).passed


def test_g1_reports_a_timeout_rather_than_hanging(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    ctx = _ctx(repo, tmp_path)
    ctx = GateContext(
        repo=ctx.repo,
        base_ref=ctx.base_ref,
        head_ref=ctx.head_ref,
        verdict=ctx.verdict,
        workdir=ctx.workdir,
        sandbox_policy=SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED, timeout_s=1.0),
    )
    gate = G1Builds(commands=(("python", "-c", "import time; time.sleep(30)"),))
    result = gate.run(ctx)
    assert not result.passed
    assert "timed out" in result.reason


# --------------------------------------------------------------------------
# The pipeline — ordering is the property
# --------------------------------------------------------------------------


class _Recorder(Gate):
    def __init__(self, gate_id: str, log: list[str], *, outcome: GateOutcome) -> None:
        self.id = gate_id
        self._log = log
        self._outcome = outcome

    def run(self, ctx: GateContext) -> GateResult:
        self._log.append(self.id)
        return GateResult(gate=self.id, outcome=self._outcome)


def test_the_pipeline_imposes_the_canonical_order(repo: GitRepo, tmp_path: Path) -> None:
    # G4 MUST run before G2: a proposal that edits its own tests is rejected
    # before it gets to run them. Ordering is imposed here, not trusted from
    # the caller's list.
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    log: list[str] = []
    gates = [
        _Recorder(gid, log, outcome=GateOutcome.PASS) for gid in ("G3", "G2", "G4", "G1", "G0")
    ]

    result = run_pipeline(gates, _ctx(repo, tmp_path))

    assert log == ["G0", "G1", "G4", "G2", "G3"]
    assert result.passed
    assert list(CANONICAL_ORDER).index("G4") < list(CANONICAL_ORDER).index("G2")


def test_the_pipeline_stops_at_the_first_failure(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    log: list[str] = []
    gates = [
        _Recorder("G0", log, outcome=GateOutcome.PASS),
        _Recorder("G1", log, outcome=GateOutcome.FAIL),
        _Recorder("G4", log, outcome=GateOutcome.PASS),
    ]

    result = run_pipeline(gates, _ctx(repo, tmp_path))

    assert log == ["G0", "G1"]  # G4 never ran — the expensive work is skipped
    assert not result.passed
    assert result.failed_at is not None
    assert result.failed_at.gate == "G1"


def test_an_unregistered_gate_id_is_refused(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    with pytest.raises(ValueError, match="canonical order"):
        run_pipeline([_Recorder("G9", [], outcome=GateOutcome.PASS)], _ctx(repo, tmp_path))


def test_an_empty_pipeline_does_not_count_as_passing(repo: GitRepo, tmp_path: Path) -> None:
    # "No gates ran" must never read as "the candidate passed".
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    assert not run_pipeline([], _ctx(repo, tmp_path)).passed


def test_the_real_gates_run_end_to_end_in_order(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "VALUE = 3\n"})
    gates = [
        G0StaticSafety(),
        G4SeparationOfPowers(),
        G1Builds(commands=(("python", "-c", "import agents.planner"),)),
    ]
    result = run_pipeline(gates, _ctx(repo, tmp_path))
    assert result.ran == ("G0", "G1", "G4")
    assert result.passed


def test_a_subverting_candidate_is_stopped_by_the_first_gate(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"aef/harness/gate.py": "MARKER = 'subverted'\n"})
    gates = [G0StaticSafety(), G4SeparationOfPowers(), G1Builds()]
    result = run_pipeline(gates, _ctx(repo, tmp_path))

    assert result.ran == ("G0",)  # never reached the expensive gates
    assert not result.passed
    assert result.security_events


# --------------------------------------------------------------------------
# ADR 0062 — unmeasurable size denies; export-ignore cannot hide the suite
# --------------------------------------------------------------------------


def test_a_change_git_will_not_size_is_rejected_not_counted_as_zero(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Measured, not hypothesised: a candidate marking its own files binary
    via agents/.gitattributes made a 5,050-line rewrite report as 1 changed
    line, because an unparseable numstat count defaulted to 0."""
    _git(repo.root, "checkout", "-qb", "cand")
    (repo.root / "agents" / ".gitattributes").write_text("*.py binary\n")
    (repo.root / "agents" / "planner.py").write_text("y = 2\n" * 5000)
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "huge, marked binary")

    ctx = _ctx(repo, tmp_path)
    assert ctx.verdict.diff.unmeasurable, "the binary-marked file should be flagged"

    result = G0StaticSafety().run(ctx)
    assert not result.passed
    assert "unmeasurable" in result.reason


def test_an_ordinary_change_is_still_measurable(repo: GitRepo, tmp_path: Path) -> None:
    _candidate(repo, {"agents/planner.py": "VALUE = 1\n"})
    ctx = _ctx(repo, tmp_path)
    assert ctx.verdict.diff.unmeasurable == ()
    assert G0StaticSafety().run(ctx).passed


def test_export_ignore_cannot_hide_the_test_suite_from_the_workspace(
    repo: GitRepo, tmp_path: Path
) -> None:
    """`git archive` honours export-ignore, so a repo that excludes tests/
    from its sdist — an ordinary thing to do — got a workspace with no test
    suite, and G1 ran a suite missing the test that fails. ls-tree ignores
    export attributes and reports the tree as committed."""
    (repo.root / "tests").mkdir(exist_ok=True)
    (repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    (repo.root / ".gitattributes").write_text("tests/ export-ignore\naef/ export-ignore\n")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "export-ignore at base")

    _candidate(repo, {"agents/planner.py": "VALUE = 2\n"})
    diff = inspect_candidate(repo, "base", "cand").diff
    dest = build_candidate_workspace(repo, diff, tmp_path / "ws")

    assert (dest / "tests" / "test_x.py").is_file(), "export-ignore hid the test suite"
    assert (dest / "aef" / "harness" / "gate.py").is_file(), "export-ignore hid the harness"


def test_the_workspace_does_not_materialise_symlinks_from_the_base_tree(
    repo: GitRepo, tmp_path: Path
) -> None:
    (repo.root / "link.py").symlink_to("agents/planner.py")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "base symlink")

    _candidate(repo, {"agents/planner.py": "VALUE = 3\n"})
    diff = inspect_candidate(repo, "base", "cand").diff
    dest = build_candidate_workspace(repo, diff, tmp_path / "ws")

    assert not (dest / "link.py").exists()
