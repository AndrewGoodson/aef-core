#!/usr/bin/env python
"""J2c — a staircase the proposer can actually climb (ADR 0203).

ADR 0198 ran the stepping-stone A/B on `agents/demo` and got
`stepping_stone_keeps = 0` with a denominator of 5: sampling built on a
rejected member five times, three generations deep, and none of the five
descendants was kept. Its own diagnosis named the missing half:

    "a rig in which a rejected candidate is on the path to a kept one *and*
     the proposer can take the second step. This rig had the first and not
     the second."

WHY THE DEMO RIG HAD ONLY THE FIRST HALF, in one sentence, because it decides
everything below: `agents/demo`'s winning square needs BOTH constants raised
coherently, `find_constants` returns them in source order, and `cycle` takes
`proposals[0]` — so from any parent whatsoever the rule-based proposal raises
`RETRY_BUDGET` and never `QUALITY_THRESHOLD`. The demo's ladder is on an axis
the proposer cannot walk.

`agents/ladder` puts the ladder on the axis the proposer DOES walk. One
constant, `BATCH_SIZE`, first in the file:

    BATCH_SIZE   task metric on the ladder corpus
    3            the blessed baseline
    4            EXACTLY the baseline — neutral, so G3 rejects it
    5            BETTER — the two `hard-5` scenarios complete
    6+           0.0 — over the transport frame, everything fails

The proposer's step from 3 is 4 and from 4 is 5 (`coerce_value`: +25%, at
least +1). So a loop that always proposes from the kept baseline proposes 4,
gets it rejected, proposes 4 again and stops on the duplicate. **The only
route to 5 is to propose FROM the rejected 4.** That is what the archive is
for, and it is the mechanism `--sample-parents` exists to exercise.

`--probe` MEASURES that table before any arm runs, the way ADR 0198 measured
its own premise, and writes `staircase.txt`. Nothing here is argued from the
agent's source; the metric is read off `aef loop score`.

THE STATISTIC, unchanged from ADR 0198 so the three measurements are
comparable: `stepping_stone_keeps` — kept members whose parent the gates
REJECTED — read from the persisted lineage through `archive.fold_lineage`,
with its denominator (`descendants_of_a_rejected_member`) beside it.

TWO SOURCES OF CHANCE, stated before the arms because both can hide a result:

1. **The cohort.** From a parent at 4 the null cohort can reach 5, 6 and 7 by
   mutating `BATCH_SIZE` (scale in [0.5, 2.0)), and a member that lands on 5
   scores what the candidate scores, so G3 rejects the candidate for not
   beating the cohort. With four constants to choose from, P(one member of
   five lands on 5) is about 0.16 — so roughly one sampling run in six is
   blocked by luck, and that is the null hypothesis working.
2. **The parent draw.** `_choose_parent` is weighted-random over the archive,
   and drawing the ROOT at turn 2 re-proposes the already-rejected 4, which
   stops the run. So a single run is a coin flip and a single run proves
   nothing either way.

Both are why every arm is run over SEEDS 0..N-1 and every seed is reported,
rather than one seed being run and quoted.

Usage:

    python docs/research/j2c/run_j2c.py --record        # build the corpus, 0 calls
    python docs/research/j2c/run_j2c.py --probe         # the staircase, 0 calls
    python docs/research/j2c/run_j2c.py --dry-run
    python docs/research/j2c/run_j2c.py --arms --seeds 8 --workroot /tmp/j2c
    python docs/research/j2c/run_j2c.py --report
    python docs/research/j2c/run_j2c.py --verify

`ClaudeCodeProvider.complete` is wrapped with a counter and a hard cap that
raises rather than spend past it. The default cap is ZERO: the ladder corpus
records no model calls, the rule-based proposer makes none, and the arms are
asserted free rather than believed free.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
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

HERE = Path(__file__).resolve().parent
AGENT_PATH = "agents/ladder/graph.py"
ENTRYPOINT = "agents.ladder.graph:build_graph"
GRAPH_ID = "ladder_agent"
CORPUS_DIR = HERE / "corpus"
DEFAULT_OUT = HERE / "results.jsonl"
ARMS = ("greedy", "sampling")

BUILD_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-c", "import agents.ladder.graph as g; g.build_graph()"),
)

# (scenario_id, split, items, expected). The ladder: three scenarios that pass
# at the baseline, two that need BATCH_SIZE = 5, and two tripwires that cannot
# pass at any BATCH_SIZE the transport frame allows.
SCENARIOS: tuple[tuple[str, str, int, str], ...] = (
    ("ladder-easy-1", "train", 1, "must_pass"),
    ("ladder-easy-2", "train", 2, "must_pass"),
    ("ladder-mid-3", "train", 3, "must_pass"),
    ("ladder-hard-5", "train", 5, "unspecified"),
    ("ladder-tripwire-train", "train", 9, "must_fail"),
    ("ladder-val-easy", "validation", 2, "must_pass"),
    ("ladder-val-mid", "validation", 3, "must_pass"),
    ("ladder-val-hard-5", "validation", 5, "unspecified"),
    ("ladder-tripwire-val", "validation", 9, "must_fail"),
)

# The recorded failure the proposer is grounded in. It names a TRAIN scenario
# (so `MemoryEvidence.from_store` admits it) and blames the node the recorded
# error actually blames.
FAILURES: tuple[tuple[str, str], ...] = (
    ("ladder-hard-5", "gave up: 5 item(s) do not fit a batch of 3 (retry delay 50ms, 2 in flight)"),
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
    original = ClaudeCodeProvider.complete

    def counted(self: ClaudeCodeProvider, request: Any) -> Any:
        counter.note()
        return original(self, request)

    ClaudeCodeProvider.complete = counted  # type: ignore[method-assign]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Recording the corpus — this worker's OWN copy, never `corpus/`
# ---------------------------------------------------------------------------


def record_corpus() -> None:
    """Record the ladder corpus by RUNNING the agent, into `docs/research/j2c/`.

    Deliberately not into `corpus/`: another worker holds that this wave, and
    "two measurement branches may not touch one corpus" is a rule of this loop
    learned the expensive way. The arms copy this directory over the clone's
    `corpus/`, so nothing about the repository's own corpus moves.

    Zero model calls — `agents/ladder` calls no model — which `--record`
    asserts by running under a counter capped at 0.
    """
    from aef.harness.checks import TaskCheck
    from aef.harness.corpus import Expected, Split, save_scenario
    from aef.harness.recorder import record_run
    from aef.services.runtime import agent_services
    from aef.state import AEFState

    sys.path.insert(0, str(REPO_ROOT))
    from agents.ladder.graph import build_graph  # noqa: PLC0415

    if CORPUS_DIR.exists():
        shutil.rmtree(CORPUS_DIR)
    checks = (
        TaskCheck(path="scores.quality", op="equals", value=1.0),
        TaskCheck(path="plan.status", op="equals", value="done"),
    )
    at = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    for scenario_id, split, items, expected in SCENARIOS:
        state = AEFState(
            run_id=scenario_id,
            agent_id=GRAPH_ID,
            objective=f"process {items} item(s) for {scenario_id}",
            working_memory={"items": items},
        )
        scenario = record_run(
            build_graph(),
            state,
            agent_services(),
            scenario_id=scenario_id,
            split=Split(split),
            recorded_at=at,
            expected=Expected(expected),
            checks=checks,
            notes=(
                f"recorded from a real agents/ladder run (items={items}); ADR 0203's "
                f"staircase fixture. This corpus is J2c's own copy and is never the "
                f"repository's `corpus/`."
            ),
        )
        path = save_scenario(CORPUS_DIR, scenario)
        print(f"  {scenario_id:24s} {split:10s} items={items:<2d} -> {path.name}")
    print(f"\nwrote {len(SCENARIOS)} scenario(s) to {CORPUS_DIR.relative_to(REPO_ROOT)}")


def prepare_arm(workroot: Path) -> Path:
    """A fresh clone with `corpus/` REPLACED by the ladder corpus.

    A clone rather than the repository itself: `run_loop` creates candidate
    branches and moves a kept branch, and a measurement that leaves refs behind
    in the tree it was run from is a measurement that changed its own subject.

    The whole corpus is replaced rather than filtered because `cycle` refuses
    an ambiguous corpus and the summary and demo scenarios would otherwise be
    gated against a graph that cannot produce them.
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
    _git(repo_dir, "config", "user.email", "j2c@aef")
    _git(repo_dir, "config", "user.name", "j2c")
    _git(repo_dir, "checkout", "-q", "-B", "main")
    shutil.rmtree(repo_dir / "corpus")
    shutil.copytree(CORPUS_DIR, repo_dir / "corpus")
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-qm", "j2c: the ladder corpus, in place of the repository's")
    return repo_dir


def write_memory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "id": f"j2c-mem-{index}",
                "kind": "failure",
                "agent_id": GRAPH_ID,
                "run_id": scenario,
                "tags": [],
                "created_at": f"2026-09-0{index}T12:00:00+00:00",
                "content": {"verbal_feedback": feedback, "failing_nodes": ["work"]},
            }
        )
        for index, (scenario, feedback) in enumerate(FAILURES, start=1)
    ]
    path.write_text("\n".join(lines) + "\n")


def bless_baseline(repo_dir: Path, state_root: Path) -> None:
    from aef.harness.preflight import bless

    bless(
        repo_root=repo_dir,
        state_root=state_root,
        agent_path=AGENT_PATH,
        graph_id=GRAPH_ID,
        at=datetime.now(UTC),
        note="j2c baseline",
        ref="main",
    )


def stepping_stone_keeps(state_root: Path) -> dict[str, Any]:
    """The number this rig exists for, read from the persisted lineage through
    `archive.fold_lineage` — THE fold, the one the driver and `aef loop lineage
    list` use. Identical to ADR 0198's function, deliberately: a statistic
    computed a second way is a statistic that will eventually disagree."""
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
    seed: int,
    workroot: Path,
    out: Path,
    turns: int,
    budget_seconds: float,
    counter: CallCounter,
) -> dict[str, Any]:
    from aef.harness.corpus import load_corpus

    arm_root = workroot / f"{arm}-seed{seed}"
    state_root = arm_root / "state"
    memory_path = arm_root / "memory.jsonl"
    repo_dir = prepare_arm(arm_root)
    write_memory(memory_path)
    bless_baseline(repo_dir, state_root)

    config = LoopConfig(
        repo=GitRepo(root=repo_dir),
        paths=LoopPaths(root=state_root),
        base_ref="main",
        graph_id=GRAPH_ID,
        corpus=load_corpus(repo_dir / "corpus"),
        entrypoint=ENTRYPOINT,
        build_commands=BUILD_COMMANDS,
        proposer="rule_based",
    )

    turn_log: list[dict[str, Any]] = []

    def logging_cycle(cfg: LoopConfig, **kw: Any) -> CycleRun:
        counter.phase = f"{arm}-seed{seed}-turn-{len(turn_log) + 1}"
        started = time.monotonic()
        run = cycle(cfg, **kw)
        entry = {
            "kind": "turn",
            "arm": arm,
            "seed": seed,
            "turn": len(turn_log) + 1,
            "proposed": run.proposed,
            "disposition": run.decision.disposition.value if run.decision else None,
            "reason": run.decision.reason if run.decision else None,
            "score": run.score,
            "incumbent_score": run.incumbent_score,
            "exit_code": run.exit_code,
            "seconds": round(time.monotonic() - started, 1),
            "batch_size": _batch_size_of(cfg, run.proposed),
            "lines": list(run.lines),
        }
        turn_log.append(entry)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return run

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
    result: dict[str, Any] = {
        "kind": "summary",
        "arm": arm,
        "seed": seed,
        "turns": len(run.turns),
        "kept": run.kept_count,
        "reverted": run.reverted_count,
        "duplicates": sum(t.duplicate for t in run.turns),
        "distinct_kept_trees": run.distinct_kept_trees,
        "distinct_parents": len({t.parent_ref for t in run.turns}),
        "halted": any(t.disposition is None for t in run.turns),
        "stopped_because": run.stopped_because,
        "trajectory": [
            {"turn": t.turn, "kept": t.kept, "score": t.score, "parent": t.parent_ref[:12]}
            for t in run.turns
        ],
        "batch_sizes": [e["batch_size"] for e in turn_log],
        "lines": list(run.lines),
        "lineage": stepping_stone_keeps(state_root),
        "calls_total": counter.calls,
    }
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result) + "\n")
    return result


def _batch_size_of(config: LoopConfig, proposed: str | None) -> int | None:
    """What `BATCH_SIZE` the candidate branch actually carries.

    Read from the branch rather than inferred from the turn number: the whole
    claim is about which rung the loop reached, and a claim about a rung is
    worth exactly as much as the file it was read from.
    """
    if proposed is None:
        return None
    try:
        source = config.repo.show(f"loop/{proposed}", AGENT_PATH)
    except Exception:  # noqa: BLE001 - a missing branch is "no rung to report"
        return None
    for line in source.splitlines():
        if line.startswith("BATCH_SIZE = "):
            return int(line.split("=", 1)[1].split("#")[0].strip())
    return None


# ---------------------------------------------------------------------------
# The staircase probe
# ---------------------------------------------------------------------------


def probe(workroot: Path) -> None:
    """The rig's premise, MEASURED — published before any arm runs.

    `PYTHONDONTWRITEBYTECODE` is not decoration. `BATCH_SIZE = 3` and
    `BATCH_SIZE = 4` are the same number of bytes and CPython invalidates a
    `.pyc` on mtime-in-seconds plus size, so rewriting the file inside one
    second silently re-runs the previous variant's bytecode. ADR 0198 found
    that the hard way and this probe inherits the fix.
    """
    repo_dir = prepare_arm(workroot / "probe")
    graph = repo_dir / AGENT_PATH
    base = graph.read_text()
    env = dict(os.environ, PYTHONPATH=str(repo_dir), PYTHONDONTWRITEBYTECODE="1")
    print("BATCH_SIZE -> task metric on the ladder corpus (train + validation)\n")
    try:
        for value in (1, 2, 3, 4, 5, 6, 7):
            graph.write_text(base.replace("BATCH_SIZE = 3", f"BATCH_SIZE = {value}", 1))
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
                    "train,validation",
                    "--json",
                ],
                cwd=repo_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise SystemExit(completed.stderr[-3000:])
            payload = json.loads(completed.stdout)
            per: dict[str, float] = {}
            passed = total = 0
            for split in ("train", "validation"):
                per.update(payload[split]["per_scenario"])
                passed += sum(1 for v in payload[split]["per_scenario"].values() if v >= 1.0)
                total += payload[split]["n"]
            note = {
                3: "   <- the blessed baseline",
                4: "   <- a step that gains nothing: EXACTLY the baseline",
                5: "   <- the rung above it: `hard-5` completes",
                6: "   <- over the 5-slot transport frame: everything fails",
            }.get(value, "")
            print(
                f"  BATCH_SIZE {value}   mean {passed / total:.4f}   "
                + "  ".join(f"{k}={v:g}" for k, v in sorted(per.items()))
                + note
            )
    finally:
        graph.write_text(base)
    print(
        "\nThe proposer's own step is +25%, at least +1 (`coerce_value`), so from 3 it\n"
        "proposes 4 and from 4 it proposes 5. Greedy proposes from the kept baseline,\n"
        "which stays at 3, so greedy proposes 4 forever and stops on the duplicate.\n"
        "The rung at 5 is reachable ONLY from the rejected 4."
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _rows(out: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not out.is_file():
        raise SystemExit(f"no results at {out}")
    turns: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for line in out.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        (turns if row.get("kind") == "turn" else summaries).append(row)
    return turns, summaries


def report(out: Path) -> None:
    turns, summaries = _rows(out)
    print("J2c — a staircase the proposer can climb (ADR 0203)\n")
    print("PER SEED")
    print(
        f"  {'arm':9s} {'seed':>4s} {'turns':>5s} {'kept':>4s} {'rev':>3s} "
        f"{'parents':>7s} {'from a reject':>13s} {'KEPT FROM ONE':>13s} "
        f"{'rungs':>16s}  stopped"
    )
    for row in sorted(summaries, key=lambda r: (str(r["arm"]), int(r["seed"]))):
        lin = row["lineage"]
        rungs = ",".join(str(b) for b in row["batch_sizes"] if b is not None)
        print(
            f"  {row['arm']:9s} {row['seed']:>4d} {row['turns']:>5d} {row['kept']:>4d} "
            f"{row['reverted']:>3d} {row['distinct_parents']:>7d} "
            f"{lin['descendants_of_a_rejected_member']:>13d} "
            f"{lin['stepping_stone_keeps']:>13d} {rungs:>16s}  {row['stopped_because'][:44]}"
        )

    print("\nBY ARM")
    print(
        f"  {'arm':9s} {'runs':>4s} {'kept':>4s} {'from a reject':>13s} "
        f"{'KEPT FROM ONE':>13s} {'reached rung 5':>14s} {'calls':>5s}"
    )
    for arm in ARMS:
        rows = [r for r in summaries if r["arm"] == arm]
        if not rows:
            continue
        reached = sum(1 for r in rows if 5 in (r["batch_sizes"] or []))
        print(
            f"  {arm:9s} {len(rows):>4d} {sum(r['kept'] for r in rows):>4d} "
            f"{sum(r['lineage']['descendants_of_a_rejected_member'] for r in rows):>13d} "
            f"**{sum(r['lineage']['stepping_stone_keeps'] for r in rows):d}**".rjust(13)
            + f" {reached:>14d} {sum(r['calls_total'] for r in rows):>5d}"
        )

    stones = [(r["arm"], r["seed"], s) for r in summaries for s in r["lineage"]["stepping_stones"]]
    print(f"\nKEPT MEMBERS DESCENDING FROM A REJECTED ONE: {len(stones)}")
    for arm, seed, stone in stones:
        print(
            f"  {arm}/seed{seed}: {stone['ref']} (score {stone['score']}) from "
            f"{stone['parent_ref']} (score {stone['parent_score']}, "
            f"{stone['parent_disposition']})"
        )
    if not stones:
        print("  none — no kept member descends from a rejected one")

    print("\nEVERY TURN")
    for row in sorted(turns, key=lambda r: (str(r["arm"]), int(r["seed"]), int(r["turn"]))):
        print(
            f"  {row['arm']:9s} seed{row['seed']} turn{row['turn']}  "
            f"BATCH_SIZE={row['batch_size']}  score={row['score']} "
            f"incumbent={row['incumbent_score']}  {row['disposition']}  "
            f"{(row['reason'] or '')[:70]}"
        )


def dry_run(seeds: int, turns: int) -> None:
    print("J2c — a staircase the proposer can climb. DRY RUN; nothing spends a call.\n")
    print(f"agent        : {AGENT_PATH}  entrypoint {ENTRYPOINT}")
    print(f"graph id     : {GRAPH_ID}")
    print(
        f"corpus       : {CORPUS_DIR.relative_to(REPO_ROOT)} "
        f"({len(SCENARIOS)} scenarios, this worker's own copy)"
    )
    print("proposer     : rule_based (offline, deterministic, 0 calls)")
    print(f"arms         : {', '.join(ARMS)} — identical but for `sample_parents`")
    print(f"seeds        : 0..{seeds - 1}, every one reported")
    print(f"turns per arm: {turns}")
    print(f"build command: {' '.join(BUILD_COMMANDS[0])}")
    print()
    print("calls: 0. The ladder corpus records no model calls, the rule-based")
    print("proposer makes none, and the counter's cap is 0 so the arms cannot")
    print("silently start spending.")
    print()
    print("THE STATISTIC: stepping_stone_keeps — kept members whose parent the")
    print("gates REJECTED. ADR 0198 measured 0 of 5 on a rig whose second rung")
    print("the proposer could not reach. This rig's second rung is on the axis")
    print("the proposer walks.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--arms", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--arm", choices=ARMS, default=None, help="one arm; default both")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--turns", type=int, default=6)
    parser.add_argument("--budget-seconds", type=float, default=1800.0)
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--workroot", type=Path, default=Path("/tmp/j2c"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    counter = CallCounter(cap=args.max_calls)
    install_counter(counter)

    if args.record:
        record_corpus()
    elif args.probe:
        probe(args.workroot)
    elif args.dry_run:
        dry_run(args.seeds, args.turns)
    elif args.arms:
        for arm in ARMS if args.arm is None else (args.arm,):
            for seed in range(args.seed_start, args.seed_start + args.seeds):
                started = time.monotonic()
                result = run_arm(
                    arm,
                    seed=seed,
                    workroot=args.workroot,
                    out=args.out,
                    turns=args.turns,
                    budget_seconds=args.budget_seconds,
                    counter=counter,
                )
                lin = result["lineage"]
                print(
                    f"{arm:9s} seed{seed}  turns={result['turns']} kept={result['kept']} "
                    f"rungs={result['batch_sizes']} "
                    f"stepping_stone_keeps={lin['stepping_stone_keeps']} "
                    f"({time.monotonic() - started:.0f}s)"
                )
        print(f"\n{counter.calls} live call(s) made")
    elif args.report or args.verify:
        report(args.out)
    else:
        parser.error("one of --record/--probe/--dry-run/--arms/--report/--verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
