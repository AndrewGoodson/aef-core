"""A10 — inflate the drift budget with bytecode.

Not one of the original seven, and better evidence than most of them: it was
reproduced twice through real `aef loop cycle` runs (ADR 0142, E1), and it is
the only attack in this suite that costs the adopter nothing to launch,
because *the adopter launches it by accident on day one*.

The mechanism. `agents/**/__pycache__/*.pyc` is Zone A. Bytecode is written
after `aef loop bless` archives the baseline and before the cycle runs, so it
exists on the candidate side only, and `structural_drift` charges every line
of it — bytecode being binary, that is a lot of lines for a one-line change.
The measured cost, re-derived rather than quoted:

    drift 0.468 / 0.500 without a .gitignore   against   0.024 with

93.5% of the budget for a ONE-LINE change, headroom 0.0325. And
`_drift_exhausted_twice` halts the loop on two consecutive drift rejections,
so an adopter starts two candidates away from a halt caused by nothing their
agent did.

The control is the `.gitignore` `aef adopt` writes. This module runs adopt,
plants the bytecode, and asks **git** — not a string search — whether it would
be committed. Then it removes the block and measures what the drift becomes.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from aef.cli.adopt import run_adopt
from aef.harness.gates.g5_rate_drift import DEFAULT_MAX_DRIFT, structural_drift

# A normal-sized agent module, so that a one-line edit really is a one-line
# edit. The defect is a RATIO, and measuring it against a one-line file would
# score 1.000 either way and prove nothing.
AGENT = "RETRY_BUDGET = 3\n" + "".join(f"LINE_{i} = {i}\n" for i in range(40))
CANDIDATE = AGENT.replace("RETRY_BUDGET = 3", "RETRY_BUDGET = 5")
# A real .pyc header plus enough marshalled-looking noise to be a normal-sized
# module's bytecode. Binary, so `_lines` sees one enormous "line" per chunk —
# which is exactly why it dominates the metric.
BYTECODE = b"\xcb\r\r\n" + bytes(range(256)) * 40


def _staged(root: Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {line for line in out.splitlines() if line}


def _plant(root: Path) -> Path:
    """A candidate's one-line edit, plus the bytecode CPython leaves behind
    when the harness imports it."""
    (root / "agents").mkdir(exist_ok=True)
    (root / "agents" / "graph.py").write_text(CANDIDATE, encoding="utf-8")
    cache = root / "agents" / "__pycache__"
    cache.mkdir(exist_ok=True)
    pyc = cache / "graph.cpython-311.pyc"
    pyc.write_bytes(BYTECODE)
    return pyc


def _adopted_repo(root: Path, git: Callable[..., None], new_repo: Callable[[Path], None]) -> None:
    new_repo(root)
    (root / "agents").mkdir()
    (root / "agents" / "graph.py").write_text(AGENT, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "before adopt")
    run_adopt(root)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "aef adopt")


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a10_adopt_writes_a_gitignore_that_git_itself_honours(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """Asked of git, not of the text. `"__pycache__" in gitignore` is
    satisfied by a COMMENT, which is its own mutation (ADR 0142)."""
    root = tmp_path / "repo"
    _adopted_repo(root, git, new_repo)
    pyc = _plant(root)
    assert pyc.is_file()

    git(root, "add", "-A")
    staged = _staged(root)
    assert "agents/graph.py" in staged, "the candidate's own edit was not staged"
    assert not [p for p in staged if p.endswith(".pyc")], (
        f"bytecode reached the index despite adopt's .gitignore: {sorted(staged)}"
    )


def test_a10_the_ignore_block_is_signed_as_adopts_own(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """So a re-run maintains it rather than appending a second copy, and so an
    adopter's own quoted marker is never mistaken for it (ADR 0172)."""
    root = tmp_path / "repo"
    _adopted_repo(root, git, new_repo)
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert "# aef:begin sha256=" in text
    assert "__pycache__/" in text


def test_a10_the_corpus_and_the_workflows_are_deliberately_not_ignored(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """The over-correction that would be worse than the defect: Zone B is
    evidence read from git, and an ignored corpus is an empty one.

    Asked of git rather than of the text, for the same reason as above — the
    generated file *mentions* both paths in a comment explaining why they are
    NOT ignored, so a substring check would report the opposite of the truth.
    """
    root = tmp_path / "repo"
    _adopted_repo(root, git, new_repo)
    for never in ("corpus/scenario_001.json", ".github/workflows/loop.yml"):
        path = root / never
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        ignored = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", never],
            capture_output=True,
        )
        assert ignored.returncode != 0, f"adopt ignores {never}, which would empty the evidence"


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a10_the_control_is_load_bearing(
    tmp_path: Path,
    git: Callable[..., None],
    new_repo: Callable[[Path], None],
    attack_log: list[str],
) -> None:
    """Delete the ignore file and re-run the same steps: the bytecode is
    staged, and `structural_drift` then charges almost the whole budget for a
    one-line change.

    Both halves are asserted because either alone is weak. "The .pyc is
    staged" says nothing about cost; "drift is high" says nothing about the
    cause.
    """
    root = tmp_path / "repo"
    _adopted_repo(root, git, new_repo)
    (root / ".gitignore").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-qm", "adopter removed the ignore file")

    pyc = _plant(root)
    git(root, "add", "-A")
    staged = _staged(root)
    assert str(pyc.relative_to(root)) in staged, (
        "the bytecode is still ignored with .gitignore deleted, so the file was not the "
        "control and this attack is not the one ADR 0142 reproduced"
    )

    baseline = {"agents/graph.py": AGENT.encode()}
    candidate = {
        "agents/graph.py": CANDIDATE.encode(),
        "agents/__pycache__/graph.cpython-311.pyc": BYTECODE,
    }
    with_bytecode = structural_drift(baseline, candidate)
    without_bytecode = structural_drift(baseline, {"agents/graph.py": CANDIDATE.encode()})
    attack_log.append(
        f"drift with bytecode {with_bytecode:.3f} vs without {without_bytecode:.3f}, "
        f"budget {DEFAULT_MAX_DRIFT:.3f}"
    )

    assert with_bytecode > without_bytecode, attack_log
    assert without_bytecode <= DEFAULT_MAX_DRIFT, attack_log
    assert with_bytecode > DEFAULT_MAX_DRIFT, (
        "committed bytecode no longer exhausts the drift budget, so the .gitignore is "
        f"buying nothing measurable: {attack_log}"
    )
