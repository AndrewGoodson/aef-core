#!/usr/bin/env python
"""J2b — does a stepping stone produce a better descendant? (ADR 0198)

ADR 0160's live A/B pre-registered **distinct KEPT trees** as the statistic
that would decide `--sample-parents`, and then kept **nothing in either arm**,
so the statistic was 0 on both sides and could not discriminate. J0b (ADR
0188) named the leftover in as many words: *"no measured run where a stepping
stone produced a better descendant."*

That is one number and this rig exists to produce it:

    **stepping_stone_keeps** — kept members whose parent is a member the gates
    REJECTED.

WHY A DIFFERENT RIG, stated first because it is the load-bearing choice.
S4 ran on `agents/summary` with two gated scenarios, and its raw results
(`docs/research/j2/results.jsonl`) say the same thing fifteen times: every
turn that reached G3 scored **0.5 against an incumbent of 0.5** and was
rejected by G2 for *"1 previously-passing scenario(s) no longer pass (zero
tolerance)"*. The candidates traded one scenario for another. For a keep to
exist on that corpus a candidate would have to score strictly above the
incumbent AND regress no scenario AND beat a five-member null cohort; nothing
in 15 turns came close, and no amount of parent sampling changes the quality
of what the proposer writes. **A statistic about which parent was chosen
cannot be measured in a rig where nothing is ever kept.**

`agents/demo` is the rig where a keep is reachable, and it was BUILT to be —
its own docstring says why it has two constants rather than one:

    "The control cohort mutates a single constant per member, so a candidate
     that raises one budget can be matched by a random change that happens to
     raise the same one. A candidate that raises *both coherently* cannot."

Measured here on the reduced demo corpus (`--probe`, and see the ADR):

    RETRY_BUDGET / QUALITY_THRESHOLD    task metric
    3 / 3  (the blessed baseline)       0.5000
    4 / 3                               0.5000   <- a step that gains nothing
    3 / 4                               0.5000   <- and neither does the other
    4 / 4                               0.6667   <- both: `hard-both-4` passes
    5 / 5                               0.8333   <- and then `hard-both-5`

That is a **stepping stone by construction**: the one-constant candidates are
neutral, so G3 rejects them (they beat neither the incumbent nor the cohort),
and the only way to 4/4 is to build ON one of those rejections. Greedy
proposes from the kept branch, which is still the baseline, so greedy can only
ever reach the neutral states. Sampling can reach 4/4 — iff the archive kept
the rejected member and `_parent_weight` lets it be a parent.

Two arms, identical but for `sample_parents`, over a fresh clone and fresh
state each:

    greedy    run_loop(..., sample_parents=False)
    sampling  run_loop(..., sample_parents=True)

and two proposers, because they answer different halves of the question:

- `--proposer rule_based` is OFFLINE and free. `RuleBasedProposer` emits its
  proposals in a fixed order and `cycle` takes `proposals[0]`, so what it
  proposes is a deterministic function of the parent source. Run it to see
  what parent diversity is worth when the proposer has none.
- `--proposer llm` costs ONE live call per turn (the demo corpus is a set of
  recorded traces with no model calls in it, so the gates replay offline even
  under `cassette_miss="fail"`), and is stochastic, so from one parent it can
  reach either constant.

Usage:

    python docs/research/j2b/run_j2b.py --probe
    python docs/research/j2b/run_j2b.py --dry-run
    python docs/research/j2b/run_j2b.py --live --arm greedy   --proposer rule_based
    python docs/research/j2b/run_j2b.py --live --arm sampling --proposer llm --turns 8
    python docs/research/j2b/run_j2b.py --report

Every model call in the process goes through `ClaudeCodeProvider.complete`,
which is wrapped with a counter and a HARD CAP that raises rather than spend
past it — the same accounting as `docs/research/j2/run_j2.py`, and under
`--proposer rule_based` it is also the assertion that the arm was free.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.harness import archive  # noqa: E402
from aef.harness.git import GitRepo  # noqa: E402
from aef.harness.loop import CycleRun, LoopConfig, LoopPaths, cycle, run_loop  # noqa: E402
from aef.harness.memory_store import FileMemoryStore  # noqa: E402
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402

AGENT_PATH = "agents/demo/graph.py"
ENTRYPOINT = "agents.demo.graph:build_graph"
GRAPH_ID = "demo_agent"
DEFAULT_OUT = REPO_ROOT / "docs" / "research" / "j2b" / "results.jsonl"
ARMS = ("greedy", "sampling")
PROPOSERS = ("rule_based", "llm")

# G1's default is `python -m pytest -q` — this repo's WHOLE suite, per
# candidate, per turn (the defect ADR 0160 found by running J2's first turn).
# G1's question here is "does the changed agent still import and build", so
# that is what it is asked.
BUILD_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-c", "import agents.demo.graph as g; g.build_graph()"),
)

# The two failures the demo corpus records and the memory the proposer is
# grounded in. Both name TRAIN scenarios, so `MemoryEvidence.from_store`
# admits them (ADR 0096), and both blame the node the proposer may edit.
FAILURES: tuple[tuple[str, str], ...] = (
    (
        "hard-both-4",
        "gave up: difficulty 4 vs budget 3, quality 4 vs threshold 3",
    ),
    (
        "hard-both-5",
        "gave up: difficulty 5 vs budget 3, quality 5 vs threshold 3",
    ),
)


class BudgetExhausted(RuntimeError):
    """The live-call cap was reached. Raised instead of making the call."""


@dataclass
class CallCounter:
    cap: int
    calls: int = 0
    by_phase: dict[str, int] = field(default_factory=dict)
    phase: str = "setup"

    def note(self) -> None:
        if self.calls >= self.cap:
            raise BudgetExhausted(
                f"live-call cap of {self.cap} reached ({self.by_phase}); refusing to spend more"
            )
        self.calls += 1
        self.by_phase[self.phase] = self.by_phase.get(self.phase, 0) + 1


def install_counter(counter: CallCounter) -> None:
    """Wrap `ClaudeCodeProvider.complete` for the whole process, at the class
    rather than at the call site: a call site added later is counted without
    anyone remembering to."""
    original = ClaudeCodeProvider.complete

    def counted(self: ClaudeCodeProvider, request: Any) -> Any:
        counter.note()
        return original(self, request)

    ClaudeCodeProvider.complete = counted  # type: ignore[method-assign]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def prepare_arm(workroot: Path) -> Path:
    """A fresh clone of this repository with the corpus reduced to `demo_agent`.

    A clone rather than the repository itself: `run_loop` creates candidate
    branches and moves a kept branch, and a measurement that leaves refs
    behind in the tree it was run from is a measurement that changed its own
    subject.

    The corpus is reduced to the scenarios whose `graph_id` is `demo_agent`
    because `cycle` refuses an ambiguous corpus (ADR 0176/0182) and because
    the summary scenarios would otherwise be gated against a graph that cannot
    produce them. Nothing else about the corpus is touched, and the manifest
    is rewritten to describe exactly what is left (the never-shrinks rule is
    about a corpus shrinking UNDER a loop, not about building a rig).
    """
    repo_dir = workroot / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    workroot.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(repo_dir)],
        check=True,
        capture_output=True,
    )
    _git(repo_dir, "config", "user.email", "j2b@aef")
    _git(repo_dir, "config", "user.name", "j2b")
    _git(repo_dir, "checkout", "-q", "-B", "main")

    manifest = json.loads((repo_dir / "corpus" / "manifest.json").read_text())
    keep: dict[str, str] = {}
    for split in ("train", "validation", "holdout"):
        split_dir = repo_dir / "corpus" / split
        if not split_dir.is_dir():
            continue
        for path in sorted(split_dir.glob("*.json")):
            payload = json.loads(path.read_text())
            if payload.get("graph_id") == GRAPH_ID:
                keep[payload["id"]] = manifest["scenarios"][payload["id"]]
            else:
                path.unlink()
    if not keep:
        raise SystemExit(f"no {GRAPH_ID} scenarios in the corpus")
    (repo_dir / "corpus" / "manifest.json").write_text(
        json.dumps({"scenarios": keep}, indent=2, sort_keys=True) + "\n"
    )
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-qm", "j2b: reduce the corpus to the demo scenarios")
    return repo_dir


def write_memory(path: Path) -> None:
    """Admissible failure memory: the two recorded failures of `agents/demo`.

    `run_id` names a TRAIN scenario in both, so `MemoryEvidence.from_store`
    admits them; `failing_nodes` names `work`, the node the recorded errors
    actually blame, which is what constrains the structural proposer to the
    node the citation names (ADR 0096).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, (scenario, feedback) in enumerate(FAILURES, start=1):
        lines.append(
            json.dumps(
                {
                    "id": f"j2b-mem-{index}",
                    "kind": "failure",
                    "agent_id": GRAPH_ID,
                    "run_id": scenario,
                    "tags": [],
                    "created_at": f"2026-09-0{index}T12:00:00+00:00",
                    "content": {"verbal_feedback": feedback, "failing_nodes": ["work"]},
                }
            )
        )
    path.write_text("\n".join(lines) + "\n")


def bless_baseline(repo_dir: Path, state_root: Path) -> None:
    from aef.harness.preflight import bless

    bless(
        repo_root=repo_dir,
        state_root=state_root,
        agent_path=AGENT_PATH,
        graph_id=GRAPH_ID,
        at=datetime.now(UTC),
        note="j2b baseline",
        ref="main",
    )


def stepping_stone_keeps(state_root: Path) -> dict[str, Any]:
    """**The number this rig exists for**, read from the persisted lineage
    rather than from an in-memory run object — so it is exactly what `aef loop
    lineage list` shows an owner, and so it survives an arm run as several
    invocations.

    A kept member whose parent is a member the gates REJECTED is a stepping
    stone that produced a better descendant. Records go through
    `archive.fold_lineage` — THE fold, the one the driver and `aef loop lineage
    list` use — rather than a third one written here; the first version of this
    function folded last-wins and was how ADR 0198's erasure defect was found.
    """
    records = archive.read_lineage(state_root / archive.LINEAGE_DIRNAME, GRAPH_ID)
    folded = archive.fold_lineage(records)
    kept_from_reject: list[dict[str, Any]] = []
    for record in folded.values():
        if not record.kept or record.parent_ref is None:
            continue
        parent = folded.get(record.parent_ref)
        if parent is not None and not parent.kept:
            kept_from_reject.append(
                {
                    "ref": record.ref[:12],
                    "score": record.score,
                    "parent_ref": parent.ref[:12],
                    "parent_score": parent.score,
                    "parent_disposition": parent.disposition,
                }
            )
    # THE DENOMINATOR, and it is the difference between "the archive was never
    # used" and "the archive was used and it did not pay". `stepping_stone_keeps`
    # alone is 0 in a run that never proposed from a rejection at all — which is
    # exactly what greedy does — so the count of candidates that WERE proposed
    # from one is reported beside it. 0 of 0 and 0 of 5 are different findings.
    from_a_stone = [
        record
        for record in folded.values()
        if record.parent_ref is not None
        and record.parent_ref in folded
        and not folded[record.parent_ref].kept
    ]
    return {
        "members": len(folded),
        "kept": sum(1 for r in folded.values() if r.kept and r.parent_ref is not None),
        "rejected": sum(1 for r in folded.values() if not r.kept),
        "descendants_of_a_rejected_member": len(from_a_stone),
        "stepping_stone_keeps": len(kept_from_reject),
        "stepping_stones": kept_from_reject,
    }


def run_arm(
    arm: str,
    *,
    proposer: str,
    workroot: Path,
    out: Path,
    turns: int,
    seed: int,
    budget_seconds: float,
    counter: CallCounter,
    model: str,
    resume: bool = False,
) -> dict[str, Any]:
    from aef.config.factory import build_model_provider
    from aef.config.schema import ModelProviderConfig
    from aef.harness.corpus import load_corpus

    arm_root = workroot / f"{proposer}-{arm}"
    state_root = arm_root / "state"
    memory_path = arm_root / "memory.jsonl"
    if resume:
        repo_dir = arm_root / "repo"
        if not repo_dir.is_dir():
            raise SystemExit(f"--resume: no arm at {arm_root}")
    else:
        repo_dir = prepare_arm(arm_root)
        write_memory(memory_path)
        bless_baseline(repo_dir, state_root)

    repo = GitRepo(root=repo_dir)
    proposer_provider = None
    if proposer == "llm":
        proposer_provider = build_model_provider(
            ModelProviderConfig(impl="claude_code", model=model)
        )
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=state_root),
        base_ref="main",
        graph_id=GRAPH_ID,
        corpus=load_corpus(repo_dir / "corpus"),
        entrypoint=ENTRYPOINT,
        build_commands=BUILD_COMMANDS,
        proposer=proposer,
        proposer_provider=proposer_provider,
        proposer_model=model if proposer == "llm" else None,
    )

    turn_log: list[dict[str, Any]] = []

    def logging_cycle(cfg: LoopConfig, **kw: Any) -> CycleRun:
        counter.phase = f"turn-{len(turn_log) + 1}"
        before = counter.calls
        started = time.monotonic()
        run = cycle(cfg, **kw)
        entry = {
            "arm": arm,
            "proposer": proposer,
            "turn": len(turn_log) + 1,
            "proposed": run.proposed,
            "disposition": run.decision.disposition.value if run.decision else None,
            "reason": run.decision.reason if run.decision else None,
            "score": run.score,
            "incumbent_score": run.incumbent_score,
            "exit_code": run.exit_code,
            "calls": counter.calls - before,
            "seconds": round(time.monotonic() - started, 1),
            "lines": list(run.lines),
        }
        turn_log.append(entry)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return run

    result: dict[str, Any]
    try:
        run = run_loop(
            config,
            now=datetime.now(UTC),
            workdir=arm_root / f"work-{int(time.time())}",
            turns=turns,
            budget_seconds=budget_seconds,
            cycle_fn=logging_cycle,
            sample_parents=arm == "sampling",
            seed=seed,
            memory=FileMemoryStore(path=memory_path),
            agent_path=AGENT_PATH,
        )
        result = {
            "arm": arm,
            "proposer": proposer,
            "kind": "summary",
            "kept": run.kept_count,
            "reverted": run.reverted_count,
            "duplicates": sum(t.duplicate for t in run.turns),
            "distinct_kept_trees": run.distinct_kept_trees,
            "distinct_gated_trees": run.distinct_gated_trees,
            "archive_members": len(run.archive),
            "stopped_because": run.stopped_because,
            "trajectory": [
                {
                    "turn": t.turn,
                    "kept": t.kept,
                    "score": t.score,
                    "parent": t.parent_ref[:12],
                }
                for t in run.turns
            ],
            "lines": list(run.lines),
        }
    except BudgetExhausted as exc:
        result = {
            "arm": arm,
            "proposer": proposer,
            "kind": "summary",
            "stopped_because": f"BUDGET EXHAUSTED: {exc}",
            "aborted": True,
        }
    result["lineage"] = stepping_stone_keeps(state_root)
    result["calls"] = counter.by_phase
    result["calls_total"] = counter.calls
    result["turns_logged"] = len(turn_log)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result) + "\n")
    return result


# ---------------------------------------------------------------------------
# The staircase probe, dry run and report
# ---------------------------------------------------------------------------


def probe(workroot: Path) -> None:
    """The rig's premise, measured rather than argued: what the task metric
    does as the two constants move.

    `PYTHONDONTWRITEBYTECODE` is not decoration. `RETRY_BUDGET = 3` and
    `RETRY_BUDGET = 4` are the same number of bytes, and CPython's pyc
    invalidation compares mtime-in-seconds and size — so rewriting the file
    inside one second silently reuses the previous variant's bytecode, and the
    first run of this probe reported 4/4 as 0.5 and 5/5 as the 4/4 numbers.
    The loop itself is immune (every turn gets its own workspace directory);
    this probe was not.
    """
    repo_dir = prepare_arm(workroot / "probe")
    graph = repo_dir / AGENT_PATH
    base = graph.read_text()
    env = dict(os.environ, PYTHONPATH=str(repo_dir), PYTHONDONTWRITEBYTECODE="1")
    print("RETRY_BUDGET / QUALITY_THRESHOLD -> task metric on the reduced demo corpus\n")
    try:
        for retry, quality in ((3, 3), (4, 3), (3, 4), (4, 4), (5, 5), (6, 6)):
            graph.write_text(
                base.replace("RETRY_BUDGET = 3", f"RETRY_BUDGET = {retry}").replace(
                    "QUALITY_THRESHOLD = 3", f"QUALITY_THRESHOLD = {quality}"
                )
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aef.cli.main",
                    "loop",
                    "score",
                    ENTRYPOINT,
                    "--corpus",
                    "corpus",
                    "--splits",
                    "train",
                    "--json",
                ],
                cwd=repo_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise SystemExit(completed.stderr[-2000:])
            train = json.loads(completed.stdout)["train"]
            per = train["per_scenario"]
            print(
                f"  {retry} / {quality}   mean {train['mean']:.4f}   "
                + "  ".join(f"{k}={v:g}" for k, v in sorted(per.items()))
            )
    finally:
        graph.write_text(base)


def relineage(workroot: Path, out: Path) -> None:
    """Re-read every arm's persisted lineage and append one record per arm.

    The lineage file is the artifact — it is what `aef loop lineage list` reads
    and what an owner inspects — so a statistic ABOUT it is re-derivable from it
    at any time, and this is the re-derivation. It exists because
    `descendants_of_a_rejected_member` was added after the arms had run: the
    honest way to add a column to a finished measurement is to recompute it
    from the raw data the measurement left behind, not to edit the rows the
    measurement wrote.
    """
    for proposer in PROPOSERS:
        for arm in ARMS:
            state_root = workroot / f"{proposer}-{arm}" / "state"
            if not (state_root / archive.LINEAGE_DIRNAME).is_dir():
                continue
            record = {
                "kind": "lineage",
                "proposer": proposer,
                "arm": arm,
                "lineage": stepping_stone_keeps(state_root),
            }
            with out.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            print(json.dumps(record))


def dry_run(turns: int, proposer: str, max_calls: int) -> None:
    print("J2b — does a stepping stone produce a better descendant? (ADR 0198)\n")
    print(f"arms          : {', '.join(ARMS)} (identical but for `sample_parents`)")
    print(f"proposer      : {proposer}")
    print(f"turns per arm : {turns}")
    print(f"agent         : {AGENT_PATH}  entrypoint {ENTRYPOINT}")
    print(f"graph id      : {GRAPH_ID}")
    print("corpus        : every demo_agent scenario; summary scenarios removed")
    print("cassette      : miss -> fail (the demo traces record no model calls)")
    print(f"build command : {' '.join(BUILD_COMMANDS[0])}")
    print()
    print("calls, per turn:")
    if proposer == "llm":
        print("  1  the LLM proposer's request")
        print("  0  the gates: the demo corpus replays with no model call at all")
    else:
        print("  0  the rule-based proposer makes none, and the gates make none")
    print()
    print(f"HARD CAP      : {max_calls} live calls; the wrapper raises rather than exceed it")
    print()
    print(
        "THE STATISTIC: stepping_stone_keeps — kept members whose parent the gates\n"
        "REJECTED, computed from <state>/lineage/demo_agent.jsonl. ADR 0160's\n"
        "distinct-kept-trees was 0 in both arms and could not discriminate; this one\n"
        "is 0 unless the archive did the thing it exists to do."
    )


def report(out: Path) -> None:
    if not out.is_file():
        raise SystemExit(f"no results at {out}")
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    turns = [r for r in rows if r.get("kind") is None]
    summaries = [r for r in rows if r.get("kind") == "summary"]
    # A `kind: "lineage"` row is a later re-read of an arm's persisted archive
    # (`--relineage`), and it supersedes the block the arm wrote inline: same
    # file, same fold, more columns.
    relineages = {
        (r["proposer"], r["arm"]): r["lineage"] for r in rows if r.get("kind") == "lineage"
    }

    # An arm may span several invocations — the wall clock, not the call
    # budget, is what ends one here — so `inv` is counted the way J2's report
    # counts it: a turn number that does not advance starts a new invocation.
    counted: dict[tuple[str, str], int] = {}
    last_turn: dict[tuple[str, str], int] = {}
    print("Per turn (invocation.turn)\n")
    print("| proposer | arm | inv | turn | disposition | score | incumbent | calls | s |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in turns:
        key = (row["proposer"], row["arm"])
        if row["turn"] <= last_turn.get(key, 0):
            counted[key] = counted.get(key, 1) + 1
        last_turn[key] = row["turn"]
        inv = counted.setdefault(key, 1)
        score = "-" if row["score"] is None else f"{row['score']:.4f}"
        incumbent = "-" if row["incumbent_score"] is None else f"{row['incumbent_score']:.4f}"
        print(
            f"| {row['proposer']} | {row['arm']} | {inv} | {row['turn']} "
            f"| {row['disposition']} | {score} | {incumbent} | {row['calls']} "
            f"| {row['seconds']} |"
        )

    # Per arm, SUMMED across an arm's invocations — except the lineage block,
    # which is taken from the LAST invocation because it is already cumulative:
    # it is read back from the file the earlier invocation wrote.
    print("\nPer arm (summed over invocations)\n")
    print(
        "| proposer | arm | turns | kept | reverted | distinct parents "
        "| distinct kept trees | from a rejected member | **kept from one** "
        "| calls | stopped |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for proposer in PROPOSERS:
        for arm in ARMS:
            mine = [r for r in summaries if r["arm"] == arm and r["proposer"] == proposer]
            if not mine:
                continue
            used = {point["parent"] for r in mine for point in r.get("trajectory", ())}
            lineage = relineages.get((proposer, arm), mine[-1].get("lineage", {}))
            print(
                f"| {proposer} | {arm} | {sum(r.get('turns_logged', 0) for r in mine)} "
                f"| {lineage.get('kept', 0)} "
                f"| {sum(r.get('reverted', 0) for r in mine)} | {len(used)} "
                f"| {mine[-1].get('distinct_kept_trees')} "
                f"| {lineage.get('descendants_of_a_rejected_member')} "
                f"| **{lineage.get('stepping_stone_keeps')}** "
                f"| {sum(r.get('calls_total', 0) for r in mine)} "
                f"| {mine[-1].get('stopped_because')} |"
            )
    print(
        "\n`kept` is read from the LINEAGE FILE, not summed from the per-invocation\n"
        "counts: a candidate kept in invocation 1 is the ROOT of invocation 2, whose own\n"
        "`kept_count` is 0. `distinct parents` is the column ADR 0160 found discriminates,\n"
        "and the one `--sample-parents` directly controls."
    )
    for row in summaries:
        key = (row["proposer"], row["arm"])
        for stone in relineages.get(key, row.get("lineage", {})).get("stepping_stones", ()):
            print(
                f"\n{row['proposer']}/{row['arm']}: KEPT {stone['ref']} (score "
                f"{stone['score']}) from REJECTED {stone['parent_ref']} "
                f"(score {stone['parent_score']}, {stone['parent_disposition']})"
            )
    if not any(v.get("stepping_stones") for v in relineages.values()) and not any(
        s.get("lineage", {}).get("stepping_stones") for s in summaries
    ):
        print("\nNo arm produced a kept candidate whose parent the gates had rejected.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="the staircase, measured")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report", action="store_true")
    # `--verify` is the shared re-runner interface (ADR 0196): an alias of
    # `--report`, so `make measure` re-derives this table from the committed
    # JSONL with no clone, no gate run and no live call.
    parser.add_argument("--verify", action="store_true", help="alias of --report")
    parser.add_argument(
        "--relineage",
        action="store_true",
        help="re-read every arm's persisted lineage and append one record per arm",
    )
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--proposer", choices=PROPOSERS, default="rule_based")
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--budget-seconds", type=float, default=540.0)
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--workroot", default=None, help="scratch root for the arm's clone")
    args = parser.parse_args(argv)
    args.report = args.report or args.verify

    if args.dry_run:
        dry_run(args.turns, args.proposer, args.max_calls)
        return 0
    if args.report:
        report(Path(args.out))
        return 0
    if args.relineage:
        if not args.workroot:
            parser.error("--relineage needs --workroot (where the arms were run)")
        relineage(Path(args.workroot), Path(args.out))
        return 0
    if args.probe:
        if not args.workroot:
            parser.error("--probe needs --workroot (a scratch directory outside the repo)")
        probe(Path(args.workroot))
        return 0
    if not args.live or not args.arm:
        parser.error(
            "one of --probe, --dry-run, --report, --relineage, or (--live --arm <arm>)"
        )
    if not args.workroot:
        parser.error("--live needs --workroot (a scratch directory outside the repo)")

    counter = CallCounter(cap=args.max_calls)
    install_counter(counter)
    result = run_arm(
        args.arm,
        proposer=args.proposer,
        workroot=Path(args.workroot),
        out=Path(args.out),
        turns=args.turns,
        seed=args.seed,
        budget_seconds=args.budget_seconds,
        counter=counter,
        model=args.model,
        resume=args.resume,
    )
    print(json.dumps(result, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
