"""G0 on a non-Python file inside Zone A (ADR 0152).

Reproduce-first, by running the gate. A repo running `--agent-root
.claude/agents` — the opt-in ADR 0152 adds so the loop can propose a change to
a *prompt* — produced a candidate whose only changed path was a persona `.md`.
G0 answered:

    G0 outcome: pass
    G0 reason: 1 file(s), 3 line(s), all Zone A, no static-safety violations

It did not crash, which was the first question. It also **skipped silently**,
which was the second: `_scan` reads only paths ending `.py`, so the phrase "no
static-safety violations" was a claim about a file the gate had never opened.
Correct behaviour, mis-reported — and for a prompt-file repo the mis-report is
the common case, not an edge one, because every proposal M4 makes has exactly
this shape.

These tests pin both halves: the gate still passes such a candidate, and it
now says how many files it read and names the ones it did not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aef.harness.candidate import inspect_candidate
from aef.harness.gates.base import GateContext, GateOutcome
from aef.harness.gates.g0_static_safety import G0StaticSafety
from aef.harness.git import GitRepo
from aef.harness.zones import ZonePolicy

PERSONA = "---\nname: persona\ndescription: a persona\n---\n\nYou are a persona.\n"

CLEAN_GRAPH = """from __future__ import annotations


def build_graph() -> None:
    return None
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(root: Path, *, base: dict[str, str], head: dict[str, str]) -> GitRepo:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    for rel, text in base.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    _git(root, "checkout", "-qb", "cand")
    for rel, text in head.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "candidate")
    return GitRepo(root)


def _run_g0(repo: GitRepo, root: Path, policy: ZonePolicy):  # type: ignore[no-untyped-def]
    verdict = inspect_candidate(repo, "main", "cand", policy)
    return verdict, G0StaticSafety().run(
        GateContext(
            repo=repo,
            base_ref="main",
            head_ref="cand",
            verdict=verdict,
            workdir=root,
            zone_policy=policy,
        )
    )


def test_g0_does_not_crash_on_a_markdown_file_in_zone_a(tmp_path: Path) -> None:
    policy = ZonePolicy(agent_root=".claude/agents")
    repo = _repo(
        tmp_path / "r",
        base={".claude/agents/persona.md": PERSONA},
        head={".claude/agents/persona.md": PERSONA + "\n## Lessons (aef)\n- Name the county.\n"},
    )
    verdict, result = _run_g0(repo, tmp_path / "r", policy)
    assert verdict.allowed, verdict.reasons
    assert result.outcome is GateOutcome.PASS


def test_g0_says_what_it_scanned_and_names_what_it_did_not(tmp_path: Path) -> None:
    """The fix. `no static-safety violations` alone was a claim about a file
    nobody read."""
    policy = ZonePolicy(agent_root=".claude/agents")
    repo = _repo(
        tmp_path / "r",
        base={".claude/agents/persona.md": PERSONA},
        head={".claude/agents/persona.md": PERSONA + "\n- one more line\n"},
    )
    _, result = _run_g0(repo, tmp_path / "r", policy)
    assert "0 Python file(s) statically scanned" in result.reason
    assert "NOT statically scanned" in result.reason
    assert result.evidence == (".claude/agents/persona.md: not Python; no static scan",)


def test_a_python_file_is_still_counted_as_scanned(tmp_path: Path) -> None:
    policy = ZonePolicy(agent_root=".claude/agents")
    repo = _repo(
        tmp_path / "r",
        base={".claude/agents/persona.md": PERSONA},
        head={
            ".claude/agents/persona.md": PERSONA + "\n- x\n",
            ".claude/agents/migrated/a/graph.py": CLEAN_GRAPH,
        },
    )
    _, result = _run_g0(repo, tmp_path / "r", policy)
    assert result.outcome is GateOutcome.PASS
    assert "1 Python file(s) statically scanned" in result.reason
    assert "1 NOT statically scanned" in result.reason


def test_a_pure_python_candidate_reports_no_unscanned_files(tmp_path: Path) -> None:
    """The default tree is unaffected: no `.md` in the diff, no extra clause,
    and no evidence line on a clean pass."""
    repo = _repo(
        tmp_path / "r",
        base={"agents/migrated/a/graph.py": CLEAN_GRAPH},
        head={"agents/migrated/a/graph.py": CLEAN_GRAPH + "\n\nX = 1\n"},
    )
    _, result = _run_g0(repo, tmp_path / "r", ZonePolicy())
    assert result.outcome is GateOutcome.PASS
    assert "NOT statically scanned" not in result.reason
    assert result.evidence == ()


def test_the_scan_still_rejects_a_forbidden_import_beside_a_markdown_file(
    tmp_path: Path,
) -> None:
    """The report change must not become a way past the gate: a `.py` in the
    same candidate is scanned exactly as before."""
    policy = ZonePolicy(agent_root=".claude/agents")
    repo = _repo(
        tmp_path / "r",
        base={".claude/agents/persona.md": PERSONA},
        head={
            ".claude/agents/persona.md": PERSONA + "\n- x\n",
            ".claude/agents/migrated/a/graph.py": "import subprocess\n\nX = subprocess\n",
        },
    )
    _, result = _run_g0(repo, tmp_path / "r", policy)
    assert result.outcome is GateOutcome.FAIL
    assert any("subprocess" in item for item in result.evidence)
