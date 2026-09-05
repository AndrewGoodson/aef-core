#!/usr/bin/env python
"""J2 — does the archive earn its keep? (ADR 0160)

ADR 0121 (I6) measured `sample_parents` buying **zero** diversity over
greedy, and said why: the rule-based proposer has one idea, so every parent
yields the same tree. ADR 0122 (I10) then measured the LLM proposer emitting
four distinct candidates per run — with kept diversity still 1. The two have
never been run together, which is what BEYOND_90 §J2 asks for: *sampling on,
LLM proposer on, enough turns to matter.*

Two arms over the same repository state, the same corpus, the same seed and
the same model:

- **sampling** — `run_loop(..., proposer="llm", sample_parents=True)`
- **greedy**   — `run_loop(..., proposer="llm", sample_parents=False)`

Everything else is held: fresh state per arm, a fresh clone of the
repository per arm, the same `--config`, `cassette_miss="live"`.

WHY THE CORPUS IS REDUCED, stated up front because it is the one place this
rig departs from the brief. A candidate that changes `draft_prompt` changes
the model request, so every cassette misses and every gated scenario is a
LIVE call. G3 scores the candidate, an incumbent and a null cohort of
`cohort_size` variants, each over every gated scenario: with the full twelve
summary train scenarios that is ~84 live calls for ONE turn, against a total
budget of 100 for the whole increment. The rig therefore gates on
`--scenarios` summary train scenarios (default 2), which makes a G3 pass
cost ~14 calls and 8 turns per arm affordable *if most turns are stopped by
a cheap gate* — which, per I10's G5 halt, is the expected shape. The
reduction changes what a task-metric number MEANS (two scenarios, not
twelve); it does not change what is being compared, because both arms see
the identical corpus.

Usage:

    python docs/research/j2/run_j2.py --dry-run
    python docs/research/j2/run_j2.py --live --arm greedy --turns 8
    python docs/research/j2/run_j2.py --live --arm sampling --turns 8
    python docs/research/j2/run_j2.py --report

Every live call in the process goes through `ClaudeCodeProvider.complete`,
which this script wraps with a counter and a HARD CAP: past `--max-calls`
the wrapper raises rather than spending another token. One JSON object per
turn is appended to `--out` as the turn lands, so a run killed by the wall
clock keeps everything it had already measured.
"""

from __future__ import annotations

import argparse
import json
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

from aef.harness.git import GitRepo  # noqa: E402
from aef.harness.loop import CycleRun, LoopConfig, LoopPaths, cycle, run_loop  # noqa: E402
from aef.harness.memory_store import FileMemoryStore  # noqa: E402
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402

AGENT_PATH = "agents/summary/graph.py"
ENTRYPOINT = "agents.summary.graph:build_graph"
GRAPH_ID = "summary_agent"
CONFIG_PATH = "docs/research/j2/aef.measurement.yaml"
DEFAULT_OUT = REPO_ROOT / "docs" / "research" / "j2" / "results.jsonl"
# Two summary TRAIN scenarios. Gated scenarios come from the train split, so
# these are what G2/G3 measure on. See the module docstring for why two.
DEFAULT_SCENARIOS = ("sum-01-kestrel-ferry", "sum-02-orchard-blight")
ARMS = ("greedy", "sampling")
# G1's default is `python -m pytest -q` — this repo's WHOLE suite, per
# candidate, per turn. The first live turn of this rig measured exactly that
# and nothing else: `G1 rejected it: build command failed (timed out)`, before
# any behavioural gate ran, on a candidate the model had just been paid to
# write. G1's question here is "does the changed agent still import and
# compile", so that is what it is asked. `aef loop run --build-command` now
# exists for the same reason (ADR 0160).
BUILD_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-c", "import agents.summary.graph as g; g.build_graph()"),
)


# ---------------------------------------------------------------------------
# Call accounting, with a hard cap
# ---------------------------------------------------------------------------


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
    """Wrap `ClaudeCodeProvider.complete` for the whole process.

    Every live call this rig can make goes through it: the LLM proposer's own
    request, and every corpus scenario the gates replay with
    `cassette_miss="live"` (the miss path builds this provider from the base
    ref's `model_provider`). Counting at the class rather than at the two call
    sites is the point — a call site added later is counted without anyone
    remembering to.
    """
    original = ClaudeCodeProvider.complete

    def counted(self: ClaudeCodeProvider, request: Any) -> Any:
        counter.note()
        return original(self, request)

    ClaudeCodeProvider.complete = counted  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# The arm's workspace
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def prepare_arm(workroot: Path, scenarios: tuple[str, ...]) -> Path:
    """A fresh clone of this repository with the corpus reduced.

    A clone rather than the repository itself: `run_loop` creates candidate
    branches and moves a kept branch, and a measurement that leaves refs
    behind in the tree it was run from is a measurement that changed its own
    subject.
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
    _git(repo_dir, "config", "user.email", "j2@aef")
    _git(repo_dir, "config", "user.name", "j2")
    # `base_ref` is "main" everywhere in the harness; the clone's HEAD is
    # whatever branch this work is on, so name it main here and stand
    # somewhere else (run_loop refuses to run while HEAD is the kept branch,
    # and `_materialise_candidate_branch` puts us back on this one).
    _git(repo_dir, "checkout", "-q", "-B", "main")

    manifest = json.loads((repo_dir / "corpus" / "manifest.json").read_text())
    keep = {name: split for name, split in manifest["scenarios"].items() if name in scenarios}
    missing = set(scenarios) - set(keep)
    if missing:
        raise SystemExit(f"no such scenario(s) in the corpus manifest: {sorted(missing)}")
    for split in ("train", "validation", "holdout"):
        split_dir = repo_dir / "corpus" / split
        if not split_dir.is_dir():
            continue
        for path in sorted(split_dir.glob("*.json")):
            if path.stem not in keep:
                path.unlink()
    (repo_dir / "corpus" / "manifest.json").write_text(
        json.dumps({"scenarios": keep}, indent=2, sort_keys=True) + "\n"
    )
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-qm", "j2: reduce the corpus to the gated scenarios")
    return repo_dir


def write_memory(path: Path, scenarios: tuple[str, ...]) -> None:
    """Admissible failure memory: two records from TRAIN scenarios.

    `MemoryEvidence.from_store` excludes records whose `run_id` names a
    validation or holdout scenario (ADR 0096). These name train scenarios, so
    they are admissible, and they describe the failure the corpus's own
    checks catch — a summary that overruns the cap or drops a required term.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, scenario in enumerate(scenarios, start=1):
        lines.append(
            json.dumps(
                {
                    "id": f"j2-mem-{index}",
                    "kind": "failure",
                    "agent_id": GRAPH_ID,
                    "run_id": scenario,
                    "tags": [],
                    "created_at": f"2026-09-0{index}T12:00:00+00:00",
                    "content": {
                        "verbal_feedback": (
                            "the summary ran over the word cap and dropped a required term"
                        ),
                        "failing_nodes": ["draft"],
                    },
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
        note="j2 baseline",
        ref="main",
    )


# ---------------------------------------------------------------------------
# One arm
# ---------------------------------------------------------------------------


def run_arm(
    arm: str,
    *,
    workroot: Path,
    out: Path,
    turns: int,
    scenarios: tuple[str, ...],
    seed: int,
    budget_seconds: float,
    counter: CallCounter,
    model: str,
    resume: bool = False,
) -> dict[str, Any]:
    from aef.config.factory import build_model_provider
    from aef.config.schema import ModelProviderConfig
    from aef.harness.corpus import load_corpus

    arm_root = workroot / arm
    state_root = arm_root / "state"
    memory_path = arm_root / "memory.jsonl"
    if resume:
        # The point of the persistence this increment built, exercised live:
        # a second invocation against the SAME state directory resumes the
        # lineage rather than starting a fresh search. Nothing is re-cloned,
        # nothing is re-blessed (`bless` refuses a second baseline anyway,
        # and rightly — it would reset the drift budget).
        repo_dir = arm_root / "repo"
        if not repo_dir.is_dir():
            raise SystemExit(f"--resume: no arm at {arm_root}")
    else:
        repo_dir = prepare_arm(arm_root, scenarios)
        write_memory(memory_path, scenarios)
        bless_baseline(repo_dir, state_root)

    repo = GitRepo(root=repo_dir)
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=state_root),
        base_ref="main",
        graph_id=GRAPH_ID,
        corpus=load_corpus(repo_dir / "corpus"),
        entrypoint=ENTRYPOINT,
        config_path=CONFIG_PATH,
        build_commands=BUILD_COMMANDS,
        cassette_miss="live",
        proposer="llm",
        proposer_provider=build_model_provider(
            ModelProviderConfig(impl="claude_code", model=model)
        ),
        proposer_model=model,
    )

    turn_log: list[dict[str, Any]] = []

    def logging_cycle(cfg: LoopConfig, **kw: Any) -> CycleRun:
        """The real `cycle`, with the turn written to disk as it lands."""
        counter.phase = f"turn-{len(turn_log) + 1}"
        before = counter.calls
        started = time.monotonic()
        try:
            run = cycle(cfg, **kw)
        except BudgetExhausted:
            raise
        entry = {
            "arm": arm,
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

    stopped = ""
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
            "kind": "summary",
            "kept": run.kept_count,
            "reverted": run.reverted_count,
            "duplicates": sum(t.duplicate for t in run.turns),
            "distinct_kept_trees": run.distinct_kept_trees,
            "distinct_gated_trees": run.distinct_gated_trees,
            "archive_members": len(run.archive),
            "stopped_because": run.stopped_because,
            "trajectory": [
                {"turn": t.turn, "kept": t.kept, "score": t.score, "parent": t.parent_ref[:12]}
                for t in run.turns
            ],
            "lines": list(run.lines),
        }
    except BudgetExhausted as exc:
        stopped = f"BUDGET EXHAUSTED: {exc}"
        result = {"arm": arm, "kind": "summary", "stopped_because": stopped, "aborted": True}
    result["calls"] = counter.by_phase
    result["calls_total"] = counter.calls
    result["turns_logged"] = len(turn_log)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result) + "\n")
    return result


# ---------------------------------------------------------------------------
# Dry run and report
# ---------------------------------------------------------------------------


def dry_run(turns: int, scenarios: tuple[str, ...], max_calls: int) -> None:
    manifest = json.loads((REPO_ROOT / "corpus" / "manifest.json").read_text())
    splits = {s: manifest["scenarios"].get(s, "MISSING") for s in scenarios}
    print("J2 — the archive A/B (ADR 0160)\n")
    print(f"arms          : {', '.join(ARMS)} (identical but for `sample_parents`)")
    print(f"turns per arm : {turns}")
    print(f"agent         : {AGENT_PATH}  entrypoint {ENTRYPOINT}")
    print(f"graph id      : {GRAPH_ID}")
    print(f"config        : {CONFIG_PATH} (read from the base ref)")
    print("cassette      : miss -> live")
    print(f"gated corpus  : {len(scenarios)} scenario(s)")
    for name, split in splits.items():
        print(f"                {name}  [{split}]")
    print()
    print("calls, per turn:")
    print("  1  the LLM proposer's request")
    print("  0  if a CHEAP gate (G0/G1/G4/G5) rejects — no corpus pass happens")
    print(
        f"  ~{(5 + 2) * len(scenarios)}  if the candidate reaches G3: "
        f"(candidate + incumbent + cohort of 5) x {len(scenarios)} scenario(s)"
    )
    print()
    print(f"HARD CAP      : {max_calls} live calls; the wrapper raises rather than exceed it")
    print(
        "The expected shape, from I10 (ADR 0122): the LLM proposer's ~28-line diff\n"
        "exhausts G5's 0.5 drift budget, so most turns cost one call and two\n"
        "consecutive drift rejections halt the arm. If that happens it is a finding\n"
        "about the drift budget under an LLM proposer, NOT a failed measurement, and\n"
        "the budget is not raised to make the run complete."
    )


def report(out: Path) -> None:
    """Aggregate the JSONL into the two tables the ADR carries.

    An arm may span several invocations — the wall clock, not the call
    budget, is what ends one here — so per-arm counts are SUMMED across a
    arm's invocations, while `distinct_gated_trees` and `archive_members`
    are taken from the LAST invocation, which is already cumulative because
    it resumed the earlier one's lineage.
    """
    if not out.is_file():
        raise SystemExit(f"no results at {out}")
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    turns = [r for r in rows if r.get("kind") != "summary"]
    summaries = [r for r in rows if r.get("kind") == "summary"]

    seen: dict[str, int] = {}
    print("Per turn (invocation.turn)\n")
    print("| arm | inv | turn | disposition | score | parent | calls | s |")
    print("|---|---|---|---|---|---|---|---|")
    counted: dict[str, int] = {}
    parents: dict[tuple[str, int, int], str] = {}
    for row in summaries:
        arm = row["arm"]
        seen[arm] = seen.get(arm, 0) + 1
        for point in row.get("trajectory", ()):
            parents[(arm, seen[arm], point["turn"])] = point["parent"]
    seen.clear()
    last_turn: dict[str, int] = {}
    for row in turns:
        arm = row["arm"]
        if row["turn"] <= last_turn.get(arm, 0):
            counted[arm] = counted.get(arm, 0) + 1
        last_turn[arm] = row["turn"]
        inv = counted.setdefault(arm, 1)
        parent = parents.get((arm, inv, row["turn"]), "?")
        print(
            f"| {arm} | {inv} | {row['turn']} | {row['disposition']} | {row['score']} "
            f"| {parent} | {row['calls']} | {row['seconds']} |"
        )

    print("\nPer arm (summed over invocations)\n")
    # `distinct parents` is the column that discriminates here, and it is the
    # one BEYOND_90 did not ask for: with nothing kept in either arm,
    # distinct-KEPT-trees is 0 on both sides and can say nothing. Distinct
    # parents is what `sample_parents` directly controls.
    print(
        "| arm | turns | kept | reverted | distinct parents | distinct kept trees "
        "| distinct gated trees | calls | stopped |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        mine = [r for r in summaries if r["arm"] == arm]
        if not mine:
            print(f"| {arm} | — | — | — | — | — | — | — | NOT RUN |")
            continue
        used = {p["parent"] for r in mine for p in r.get("trajectory", ())}
        print(
            f"| {arm} | {sum(r.get('turns_logged', 0) for r in mine)} "
            f"| {sum(r.get('kept', 0) for r in mine)} "
            f"| {sum(r.get('reverted', 0) for r in mine)} "
            f"| {len(used)} "
            f"| {mine[-1].get('distinct_kept_trees')} "
            f"| {mine[-1].get('distinct_gated_trees')} "
            f"| {sum(r.get('calls_total', 0) for r in mine)} "
            f"| {mine[-1].get('stopped_because')} |"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="continue an arm already prepared: same repo, same state, same lineage. "
        "The wall clock, not the call budget, is what stops an arm here — this is how "
        "an 8-turn arm is run as two invocations, and it only works because the "
        "lineage persists (ADR 0160).",
    )
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--budget-seconds", type=float, default=540.0)
    parser.add_argument("--max-calls", type=int, default=50)
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--scenarios", nargs="*", default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--workroot", default=None, help="scratch root for the arm's clone")
    args = parser.parse_args(argv)

    scenarios = tuple(args.scenarios)
    if args.dry_run:
        dry_run(args.turns, scenarios, args.max_calls)
        return 0
    if args.report:
        report(Path(args.out))
        return 0
    if not args.live or not args.arm:
        parser.error("one of --dry-run, --report, or (--live --arm <arm>)")

    if not args.workroot:
        parser.error("--live needs --workroot (a scratch directory outside the repo)")
    counter = CallCounter(cap=args.max_calls)
    install_counter(counter)
    result = run_arm(
        args.arm,
        workroot=Path(args.workroot),
        out=Path(args.out),
        turns=args.turns,
        scenarios=scenarios,
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
