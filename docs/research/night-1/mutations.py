"""ADR 0200's mutations.

Each one removes a control this increment added, asserts the patch APPLIED
(an anchor that must be present, so a silently-missed substitution cannot be
read as a non-detection), runs the tests that should notice, then restores
from a shasum-verified backup and re-checks the digest.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/raptor/aef-core/.claude/worktrees/agent-a6db367f8d61f9cc2")
VENV = "/Users/raptor/aef-core/.venv/bin/python"
BASETEMP = (
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/p1/pt"
)

LOOP = "aef/harness/loop.py"
CLI = "aef/cli/loop.py"
WF = ".github/workflows/loop-monitor.yml"

CAND = "tests/harness/test_candidates_and_audit.py"
RUNL = "tests/harness/test_run_loop.py"
WFT = "tests/harness/test_workflows.py"
GID = "tests/cli/test_loop_cycle_graph_id.py"

MUTATIONS: list[tuple[str, str, str, str, list[str]]] = [
    (
        "M1",
        "candidates_per_turn ignored — the turn takes one, as it always did",
        LOOP,
        "chosen = _candidates_for_this_turn(proposals, config.candidates_per_turn)"
        "|||chosen = _candidates_for_this_turn(proposals, 1)",
        [CAND],
    ),
    (
        "M2",
        "the turn keeps the FIRST candidate rather than the best that passed",
        LOOP,
        "    passed = [(i, a) for i, a in enumerate(attempts) if a.passed]\n"
        "    if not passed:\n"
        "        return 0"
        "|||    passed = [(i, a) for i, a in enumerate(attempts) if a.passed]\n"
        "    if True:\n"
        "        return 0",
        [CAND],
    ),
    (
        "M3",
        "a candidate the gates REJECTED can be kept if it scored well",
        LOOP,
        "    passed = [(i, a) for i, a in enumerate(attempts) if a.passed]"
        "|||    passed = [(i, a) for i, a in enumerate(attempts)]",
        [CAND],
    ),
    (
        "M4",
        "the ledger roster is dropped — only the winner is recorded",
        LOOP,
        "            kind=ledger.EventKind.CANDIDATES,"
        "|||            kind=ledger.EventKind.GATED,",
        [CAND],
    ),
    (
        "M5",
        "every candidate shares one workdir (ADR 0122's defect, reinstated)",
        LOOP,
        "        candidate_workdir = workdir if one else workdir / f\"cand-{index}\""
        "|||        candidate_workdir = workdir",
        [CAND],
    ),
    (
        "M6",
        "audit_slice gains an input the loop controls",
        LOOP,
        "def audit_slice(corpus: Corpus | None, *, at: datetime, size: int) -> AuditSlice:"
        "|||def audit_slice(\n"
        "    corpus: Corpus | None, *, at: datetime, size: int, score: float = 0.0\n"
        ") -> AuditSlice:",
        [CAND],
    ),
    (
        "M7",
        "the held-back scenarios are gated after all",
        LOOP,
        "        scenarios = tuple(s for s in scenarios if s.id not in set(held.ids))"
        "|||        scenarios = tuple(s for s in scenarios)",
        [CAND],
    ),
    (
        "M8",
        "the held-back scenarios' records stay admissible evidence",
        LOOP,
        "    if config.corpus is None or held.is_empty:\n        return config.corpus"
        "|||    if True:\n        return config.corpus",
        [CAND],
    ),
    (
        "M9",
        "the audit is read even when no candidate passed the gates",
        LOOP,
        "    if not held.is_empty and winner.passed and not halted:"
        "|||    if not held.is_empty and not halted:",
        [CAND],
    ),
    (
        "M10",
        "a losing candidate's rejected tree is forgotten",
        LOOP,
        "        for loser in run.losers:\n"
        "            if not loser.passed:\n"
        "                rejected_trees.add(_tree_of(config, loser.branch))"
        "|||        for loser in run.losers:\n"
        "            if False:\n"
        "                rejected_trees.add(_tree_of(config, loser.branch))",
        [RUNL],
    ),
    (
        "M11",
        "`loop run` stops deriving the evidence id from the corpus (the night's defect)",
        CLI,
        "        resolution = resolve_graph_id_from_corpus(args)\n"
        "        if resolution.note is not None:\n"
        "            print(f\"  {resolution.note}\")\n"
        "        config = _config(args)"
        "|||        config = _config(args)",
        [GID],
    ),
    (
        "M12",
        "the nightly stops holding anything back",
        WF,
        "            --candidates 2 --audit-slice 1 \\\n"
        "|||",
        [WFT],
    ),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(paths: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        [
            VENV,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:warnings",
            f"--basetemp={BASETEMP}",
            "-x",
            *paths,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            "PATH": "/Users/raptor/aef-core/.venv/bin:/usr/bin:/bin",
            "HOME": "/Users/raptor",
            "PYTHONPATH": str(ROOT),
        },
    )
    tail = (proc.stdout or proc.stderr).strip().splitlines()
    return proc.returncode == 0, tail[-1] if tail else "(no output)"


def main() -> int:
    backups = {}
    for name in {m[2] for m in MUTATIONS}:
        src = ROOT / name
        dst = Path(f"{BASETEMP}/../backup-{name.replace('/', '_')}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        backups[name] = (dst, digest(src))

    detected = 0
    for tag, what, target, patch, tests in MUTATIONS:
        old, new = patch.split("|||")
        path = ROOT / target
        source = path.read_text()
        if source.count(old) != 1:
            print(f"{tag}  ANCHOR MISSING ({source.count(old)} occurrences) — {what}")
            return 2
        path.write_text(source.replace(old, new))
        assert path.read_text() != source, f"{tag}: the patch did not apply"

        ok, line = run_tests(tests)
        verdict = "NOT DETECTED" if ok else "detected"
        detected += 0 if ok else 1
        print(f"{tag}  {verdict:<12} {what}\n      {line}")

        backup, want = backups[target]
        shutil.copy2(backup, path)
        got = digest(path)
        assert got == want, f"{tag}: restore mismatch {got} != {want}"

    print(f"\n{detected}/{len(MUTATIONS)} detected")
    return 0 if detected == len(MUTATIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
