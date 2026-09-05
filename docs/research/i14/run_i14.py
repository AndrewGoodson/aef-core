#!/usr/bin/env python
"""I14 — the judge A/B, as an artifact rather than a docstring (ADR 0159).

ADR 0123 (increment I11) reported that on the 18 summary states the
rule-based judge agreed with the owner's checks 3/18 and the LLM judge 9/18.
J0's independent score (ADR 0151) deducted a point because that A/B existed
"only as a docstring citing an ADR — no test, script or committed data".
This script is the answer: it is the measurement, it lives in the repo, and
`--dry-run` shows exactly which states and which calls it would use before
a single token is spent.

Two arms over the same 18 states, on the same model, in one run:

- **rule-based** — `RuleBasedJudge(rubric={"quality": 1.0})`, no model call.
- **llm** — `LLMJudge(..., position_swap=True)`, two calls per state (the
  evidence in both orders), so 36 calls for the corpus.

The state each judge sees is the state the reflect node sees in production:
the `input_state` of the trace record whose `node_id` is `reflect`. Nothing
is reconstructed by hand — the scenario is loaded with the repo's own
`load_scenario`, the checks with the repo's own `evaluate_checks`.

**Agreement is defined here, once, because I11 committed no data to read it
off.** Each side is binarised: the owner's verdict is "pass" iff every check
in the scenario holds on the final state; a judge's verdict is "pass" iff
its score is >= `--threshold` (default 0.5). Agreement is the two verdicts
matching. The definition is checkable rather than asserted: under it the
rule-based arm can only agree on the states whose checks fail (this agent
never writes `state.scores`, so its weighted score is 0.0 everywhere), which
is how I11 got 3/18 — and `--report` prints an agreement-vs-threshold sweep
so the headline does not rest on one arbitrary cut.

Usage:

    python docs/research/i14/run_i14.py --dry-run
    python docs/research/i14/run_i14.py --live --batch-start 0 --batch-size 6
    python docs/research/i14/run_i14.py --report

`--live` appends one JSON object per state to `--out` as each judgment
lands, and skips states already present there, so a batch that dies halfway
costs only the calls it had not yet made.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.harness.checks import TaskCheck, evaluate_checks  # noqa: E402
from aef.harness.corpus import Scenario, load_scenario  # noqa: E402
from aef.providers.base import (  # noqa: E402
    CompletionRequest,
    CompletionResult,
    ModelProvider,
)
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402
from aef.reasoning.llm_reflection import LLMJudge  # noqa: E402
from aef.reasoning.rule_based_reflection import RuleBasedJudge  # noqa: E402
from aef.state import AEFState  # noqa: E402

# The 18 states of I11's A/B: every `summary_agent` scenario in train and
# validation. The two holdout scenarios are excluded — spending the holdout
# needs `--i-am-spending-the-holdout` and this measurement does not need it.
SUMMARY_GRAPH_ID = "summary_agent"
SPLITS = ("train", "validation")
RUBRIC: dict[str, float] = {"quality": 1.0}
JUDGED_NODE = "reflect"
DEFAULT_OUT = REPO_ROOT / "docs" / "research" / "i14" / "results.jsonl"
_DELTA_RE = re.compile(r"position_delta=([0-9.eE+-]+)")


@dataclass(frozen=True)
class Case:
    scenario: Scenario
    judged_state: AEFState  # what the reflect node hands the judge
    final_state: AEFState  # what the owner's checks are evaluated against


class _Recorder(ModelProvider):
    """Delegates to the real provider and keeps what answered. The judge is
    given the model name it asked for; the ANSWERING model is what the ADR
    has to name, and only the provider's result knows it."""

    name = "recording"

    def __init__(self, inner: ModelProvider) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        result = self._inner.complete(request)
        self.calls.append(
            {
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "stop_reason": result.stop_reason,
            }
        )
        return result

    def drain(self) -> list[dict[str, Any]]:
        calls, self.calls = self.calls, []
        return calls


def _final_state(scenario: Scenario) -> AEFState:
    last = scenario.trace[-1]
    return last.delta.apply(last.input_state)


def _judged_state(scenario: Scenario) -> AEFState:
    for record in scenario.trace:
        if record.node_id == JUDGED_NODE:
            return record.input_state
    raise SystemExit(f"{scenario.id}: no {JUDGED_NODE!r} record in the trace")


def load_cases(corpus_root: Path) -> list[Case]:
    cases: list[Case] = []
    for split in SPLITS:
        for path in sorted((corpus_root / split).glob("*.json")):
            scenario = load_scenario(path)
            if scenario.graph_id != SUMMARY_GRAPH_ID:
                continue
            cases.append(
                Case(
                    scenario=scenario,
                    judged_state=_judged_state(scenario),
                    final_state=_final_state(scenario),
                )
            )
    return sorted(cases, key=lambda c: c.scenario.id)


def _owner_row(case: Case) -> dict[str, Any]:
    report = evaluate_checks(case.scenario.checks, case.final_state)
    rule = RuleBasedJudge(rubric=RUBRIC).judge(case.judged_state)
    return {
        "id": case.scenario.id,
        "split": str(case.scenario.split),
        "checks_passed": report.passed,
        "checks_total": report.total,
        "owner_pass": report.passed == report.total,
        "check_failures": list(report.failures),
        "rule_score": rule.score,
        "rule_rationale": rule.rationale,
        "evidence_has_answer": bool(case.judged_state.working_memory.get("summary")),
    }


def _case_insensitive(checks: Sequence[TaskCheck]) -> tuple[TaskCheck, ...]:
    """The same checks with `contains` made case-insensitive, as the SECOND
    oracle. ADR 0123 already recorded that the corpus's only three failures
    are a capitalised term at the start of a sentence meeting a
    case-sensitive `contains`; a judge is not blind for disagreeing with a
    check that is itself wrong, so the A/B is reported against both oracles
    and neither is called the truth on its own."""
    out: list[TaskCheck] = []
    for check in checks:
        if check.op == "contains" and isinstance(check.value, str):
            out.append(
                TaskCheck(path=check.path, op="regex", value="(?i)" + re.escape(check.value))
            )
        else:
            out.append(check)
    return tuple(out)


def _read_done(out: Path) -> set[str]:
    if not out.exists():
        return set()
    done: set[str] = set()
    for line in out.read_text().splitlines():
        if line.strip():
            done.add(str(json.loads(line)["id"]))
    return done


def _batch(cases: Sequence[Case], start: int, size: int) -> Iterator[Case]:
    yield from cases[start : start + size]


def run_live(cases: Sequence[Case], out: Path, model: str, *, resume: bool) -> int:
    """One LLM judgment per case (2 calls each, position-swapped). Returns
    calls made. Every row is flushed before the next call starts."""
    provider = _Recorder(ClaudeCodeProvider(default_model=model or None))
    judge = LLMJudge(provider=provider, model=model, rubric=RUBRIC, position_swap=True)
    done = _read_done(out) if resume else set()
    calls = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as handle:
        for case in cases:
            if case.scenario.id in done:
                print(f"skip {case.scenario.id} (already in {out.name})")
                continue
            row = _owner_row(case)
            started = time.monotonic()
            judgment = judge.judge(case.judged_state)
            elapsed = time.monotonic() - started
            made = provider.drain()
            calls += len(made)
            match = _DELTA_RE.search(judgment.rationale)
            row.update(
                {
                    "llm_score": judgment.score,
                    "llm_rationale": judgment.rationale,
                    "position_delta": float(match.group(1)) if match else None,
                    "fell_back": "llm judge fell back" in judgment.rationale,
                    "elapsed_s": round(elapsed, 2),
                    "model_requested": model or "(session default)",
                    "model_answered": sorted({str(c["model"]) for c in made}),
                    "calls": made,
                }
            )
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            print(
                f"{case.scenario.id}: owner={'pass' if row['owner_pass'] else 'FAIL'} "
                f"rule={row['rule_score']:.3f} llm={judgment.score:.3f} "
                f"delta={row['position_delta']} {elapsed:.1f}s"
            )
    return calls


def dry_run(cases: Sequence[Case]) -> None:
    print(
        f"{len(cases)} summary states (graph_id={SUMMARY_GRAPH_ID}), judged at node {JUDGED_NODE!r}"
    )
    print(
        f"{2 * len(cases)} live calls if run with --live (2 per state: evidence forward + reversed)"
    )
    print()
    header = (
        f"{'id':<26} {'split':<11} {'checks':>7} {'owner':<6} "
        f"{'rule':>6} {'answer in evidence':>19}"
    )
    print(header)
    print("-" * len(header))
    for case in cases:
        row = _owner_row(case)
        print(
            f"{row['id']:<26} {row['split']:<11} "
            f"{row['checks_passed']}/{row['checks_total']:<5} "
            f"{'pass' if row['owner_pass'] else 'FAIL':<6} {row['rule_score']:>6.3f} "
            f"{str(row['evidence_has_answer']):>19}"
        )


def _verdicts(rows: list[dict[str, Any]], key: str, threshold: float) -> list[bool]:
    return [float(row[key]) >= threshold for row in rows]


def _auc(positives: list[float], negatives: list[float]) -> float | None:
    """P(a random owner-pass state scores above a random owner-fail one),
    ties at half. 0.5 is no separation — a judge whose score carries no
    information about whether the checks hold. This is the statistic the
    agreement count cannot give: on a corpus that is 15/18 pass, a judge
    that answers "pass" to everything scores 15/18 with an AUC of 0.5."""
    if not positives or not negatives:
        return None
    pairs = [(p, n) for p in positives for n in negatives]
    return sum((p > n) + 0.5 * (p == n) for p, n in pairs) / len(pairs)


def _agree(left: list[bool], right: list[bool]) -> int:
    return sum(a == b for a, b in zip(left, right, strict=True))


def _oracle_block(
    name: str, owner: list[bool], rule: list[bool], llm: list[bool], scores: list[float]
) -> None:
    n = len(owner)
    base = max(sum(owner), n - sum(owner))
    print(f"--- oracle {name}: {sum(owner)}/{n} pass; a constant answer scores {base}/{n} ---")
    print(f"  rule-based agrees: {_agree(rule, owner)}/{n}")
    print(f"  LLM        agrees: {_agree(llm, owner)}/{n}")
    auc = _auc(
        [s for s, o in zip(scores, owner, strict=True) if o],
        [s for s, o in zip(scores, owner, strict=True) if not o],
    )
    print(
        f"  LLM score AUC(pass > fail): {'n/a (one class only)' if auc is None else f'{auc:.3f}'}"
    )


def report(out: Path, threshold: float, corpus_root: Path) -> None:
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    rows.sort(key=lambda r: str(r["id"]))
    scored = [r for r in rows if r.get("llm_score") is not None]
    owner = [bool(r["owner_pass"]) for r in scored]
    rule = _verdicts(scored, "rule_score", threshold)
    llm = _verdicts(scored, "llm_score", threshold)
    n = len(scored)
    models = sorted({m for r in scored for m in r.get("model_answered", [])})
    made = [c for r in scored for c in r.get("calls", [])]
    print(f"{n} states scored; threshold {threshold}; answering model(s): {models}")
    print(
        f"{len(made)} calls; input tokens total {sum(int(c['input_tokens']) for c in made)}, "
        f"output tokens total {sum(int(c['output_tokens']) for c in made)}"
    )
    print()
    print(f"rule-based agrees with the owner checks: {_agree(rule, owner)}/{n}")
    print(f"LLM        agrees with the owner checks: {_agree(llm, owner)}/{n}")
    print(f"the two judges agree with each other:    {_agree(rule, llm)}/{n}")
    print()
    print("2x2, rule-based verdict x LLM verdict (cell = count, [k owner-pass]):")
    print(f"{'':<14}{'llm pass':>12}{'llm fail':>12}")
    for r_v, r_name in ((True, "rule pass"), (False, "rule fail")):
        cells = []
        for l_v in (True, False):
            idx = [i for i in range(n) if rule[i] == r_v and llm[i] == l_v]
            cells.append(f"{len(idx)} [{sum(owner[i] for i in idx)}]")
        print(f"{r_name:<14}{cells[0]:>12}{cells[1]:>12}")
    print()
    deltas = [r["position_delta"] for r in scored if r.get("position_delta") is not None]
    if deltas:
        print(
            f"position delta: max {max(deltas):.4g}, mean {sum(deltas) / len(deltas):.4g}, "
            f"nonzero on {sum(1 for d in deltas if d > 0)}/{len(deltas)}"
        )
    elapsed = [r["elapsed_s"] for r in scored if r.get("elapsed_s") is not None]
    if elapsed:
        print(
            f"per-judgment wall clock: mean {sum(elapsed) / len(elapsed):.1f}s, "
            f"max {max(elapsed):.1f}s"
        )
    print(f"fell back to rule-based: {sum(1 for r in scored if r.get('fell_back'))}/{n}")
    print()
    print("agreement vs threshold (the headline should not rest on one cut):")
    print(f"{'threshold':>10}{'rule':>8}{'llm':>8}")
    for cut in (0.25, 0.4, 0.5, 0.6, 0.75):
        r_v = _verdicts(scored, "rule_score", cut)
        l_v = _verdicts(scored, "llm_score", cut)
        print(f"{cut:>10}{_agree(r_v, owner):>8}{_agree(l_v, owner):>8}")
    print()
    scores = [float(r["llm_score"]) for r in scored]
    by_id = {c.scenario.id: c for c in load_cases(corpus_root)}
    owner_ci = [
        evaluate_checks(
            _case_insensitive(by_id[str(r["id"])].scenario.checks), by_id[str(r["id"])].final_state
        ).fraction
        == 1.0
        for r in scored
    ]
    print("the same A/B against two oracles — see `_case_insensitive`:")
    _oracle_block("A (the corpus's checks as written)", owner, rule, llm, scores)
    _oracle_block("B (contains made case-insensitive)", owner_ci, rule, llm, scores)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="list the states and the calls, spend nothing"
    )
    mode.add_argument("--live", action="store_true", help="make the calls")
    mode.add_argument("--report", action="store_true", help="summarise an existing results file")
    # `--verify` is the shared re-runner interface (ADR 0196): an alias of
    # `--report`, so `docs/research/measure.py` can invoke every runner the
    # same way. Re-derives the published table from the committed results
    # file; zero live calls.
    mode.add_argument("--verify", action="store_true", help="alias of --report (ADR 0196)")
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "corpus")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--batch-start", type=int, default=0)
    parser.add_argument(
        "--batch-size", type=int, default=6, help="states per invocation (2 calls each)"
    )
    parser.add_argument("--model", default="", help="empty = the harness session's default model")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--no-resume", action="store_true", help="re-judge states already in --out")
    args = parser.parse_args(argv)
    args.report = args.report or args.verify

    if args.report:
        report(args.out, args.threshold, args.corpus)
        return 0

    cases = load_cases(args.corpus)
    if args.dry_run:
        dry_run(cases)
        return 0

    batch = list(_batch(cases, args.batch_start, args.batch_size))
    print(
        f"live: {len(batch)} state(s) from index {args.batch_start}, up to {2 * len(batch)} calls"
    )
    calls = run_live(batch, args.out, args.model, resume=not args.no_resume)
    print(f"calls made this invocation: {calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
