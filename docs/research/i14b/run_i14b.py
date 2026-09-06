#!/usr/bin/env python
"""I14b — a fair test for the judge (ADR 0202).

ADR 0171 moved rubric dimension 3 to 7 on an AUC of 1.000, and closed by
saying what that number is worth:

    "AUC 1.000 is perfect separation of ONE failure family with n = 4: every
     negative is a word-cap overrun, so what has been shown is that this
     judge detects that failure, not that it detects failure."

`len(summary.split()) > cap` detects a word-cap overrun. No judge is needed.
This rig builds the set that a word count cannot grade and re-runs the
comparison on it.

**The hard set.** Six passages from `corpus/`, each contributing a MATCHED
PAIR: the agent's own recorded summary verbatim, and that same summary with
ONE minimal owner-authored edit that makes it wrong about the passage. The
judged state is the real scenario's `reflect` `input_state` with
`working_memory.summary` replaced and nothing else touched, so within a pair
the passage, the objective, the cap and the must-mention terms are identical
and the summary is the only variable.

**The negatives are AUTHORED, not observed, and that is the artifact's
weakness rather than a detail.** ADR 0171 recorded nineteen new runs against
deliberately trappy passages to obtain content negatives and got none —
"every content trap was handled correctly". A set of content negatives
cannot be recorded from this agent at this cap range. So this set grades the
JUDGE; no number from it is a statement about how often the agent fails.

**The control that makes it fair.** Every one of the twelve summaries is
within its own word cap — asserted by `--build`, which refuses to write the
file otherwise. So the word-count instrument that ADR 0171's AUC actually
measured scores exactly 6/12 here, the same as answering "pass" to
everything. Both are printed as computed numbers in `--report`.

Three arms over the same 12 cases:

    rule-based   RuleBasedJudge(rubric={"quality": 1.0})       0 calls
    llm-opus     LLMJudge, session default, position-swapped   24 calls
    llm-sonnet   LLMJudge, `--model sonnet`, position-swapped  24 calls

`claude-opus-5[1m]` wrote every positive and is the source text of every
negative, so `llm-opus` grades its own writing and `llm-sonnet`
(`claude-sonnet-5`, ADR 0162's disinterested judge, reused so the two
measurements share a third party) wrote none of it. The difference between
them on the same cases is a self-preference control on the GRADING path.

And `--live-choose` puts `PairwiseRanker` — the object ADR 0162 built and
nothing calls — on an act that CHOOSES: for each pair, pick the summary to
keep. ADR 0162's own "why 8 and not 9" asked for exactly that.

Usage:

    python docs/research/i14b/run_i14b.py --build
    python docs/research/i14b/run_i14b.py --dry-run
    python docs/research/i14b/run_i14b.py --live-grade --judge opus --batch-size 4
    python docs/research/i14b/run_i14b.py --live-choose --judge sonnet
    python docs/research/i14b/run_i14b.py --guard-demo
    python docs/research/i14b/run_i14b.py --report

`--live-grade` and `--live-choose` append one JSON object per case as each
judgment lands and skip work already present in the output file, so a batch
that dies halfway costs only the calls it had not yet made.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.harness.checks import evaluate_checks  # noqa: E402
from aef.harness.corpus import Scenario, load_scenario  # noqa: E402
from aef.providers.base import (  # noqa: E402
    CompletionRequest,
    CompletionResult,
    ModelProvider,
)
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402
from aef.reasoning.llm_reflection import (  # noqa: E402
    Candidate,
    LLMJudge,
    PairwiseRanker,
    SelfRankingError,
)
from aef.reasoning.rule_based_reflection import RuleBasedJudge  # noqa: E402
from aef.state import AEFState  # noqa: E402

HERE = Path(__file__).resolve().parent
CORPUS = REPO_ROOT / "corpus"
HARDSET = HERE / "hardset.json"
GRADES = HERE / "grades.jsonl"
CHOICES = HERE / "choices.jsonl"
RUBRIC: dict[str, float] = {"quality": 1.0}
JUDGED_NODE = "reflect"
JUDGES: dict[str, str] = {"opus": "", "sonnet": "sonnet"}
_DELTA_RE = re.compile(r"position_delta=([0-9.eE+-]+)")


@dataclass(frozen=True)
class Edit:
    """One passage's corruption: a family, a contiguous span replacement, and
    the owner's one-sentence justification for the label it produces.

    `old` must occur EXACTLY ONCE in the recorded summary — `build` raises
    otherwise. A replacement that matched twice, or not at all, would make
    the "one minimal edit" claim untrue in a way a reader could not see.
    """

    scenario_id: str
    family: str
    old: str
    new: str
    owner_reason: str


# Six families, one per passage, fixed in `prereg.txt` before any of them was
# written. The owner's reason is the label; it is a sentence a reader can
# dispute, and disputing it is the point of writing it down.
EDITS: tuple[Edit, ...] = (
    Edit(
        scenario_id="sum-31-quernmore-kiln",
        family="wrong-unit",
        old="340mm",
        new="340cm",
        owner_reason=(
            "The survey says the brick shell leans 340 MILLIMETRES out of plumb at the crown. "
            "The summary says 340 centimetres — 3.4 metres, ten times the lean, and a "
            "different fact about the building. The number is right and the unit is not."
        ),
    ),
    Edit(
        scenario_id="sum-29-brindle-viaduct",
        family="superseded-figure",
        old="from eighteen months and £2.4m to nine months and £3.1m",
        new="from eighteen months and £3.1m to nine months and £2.4m",
        owner_reason=(
            "The FIRST assessment was eighteen months and 2.4 million pounds; the revised "
            "scheme published in August is nine months and 3.1 million. The summary reports "
            "the revised cost as the original and the superseded cost as the outcome, so a "
            "reader is told the scheme got cheaper when it got dearer."
        ),
    ),
    Edit(
        scenario_id="sum-32-hessle-mills",
        family="swapped-entities",
        old=(
            "Hessle Low Mill, a listed tower mill, wins £74,000 for cap and sails, "
            "while Hessle High Mill's"
        ),
        new=(
            "Hessle High Mill, a listed tower mill, wins £74,000 for cap and sails, "
            "while Hessle Low Mill's"
        ),
        owner_reason=(
            "The grant was awarded to Hessle Low Mill and refused to Hessle High Mill. The "
            "summary reverses the two names, so the award, the sum, the mill type and the "
            "refusal are each attached to the wrong mill — the answer to the neighbouring "
            "question, told confidently."
        ),
    ),
    Edit(
        scenario_id="sum-21-ardvey-ferry",
        family="fabricated-reason",
        old="blaming an unapplied eleven-month-old chart correction",
        new="blaming a steering gear failure reported twice before",
        owner_reason=(
            "The inquiry's conclusions — no overloading, 415,000 pounds — survive, and the "
            "cause it identifies is a chart correction issued eleven months earlier and never "
            "applied to the bridge chart in use that night. A steering-gear failure reported "
            "twice before appears nowhere in the passage; the conclusion is right and the "
            "reason is invented."
        ),
    ),
    Edit(
        scenario_id="sum-38-bewick-refusals",
        family="dropped-condition",
        old=(
            "Bewick's licence refusal rate dropped from 9 to 6 per cent, though refusals "
            "rose from 41 to 58 as applications nearly doubled."
        ),
        new=(
            "Bewick's licence refusals rose from 41 to 58 last year, a marked increase on "
            "the previous year's total."
        ),
        owner_reason=(
            "The passage's finding is that the refusal RATE fell from 9 to 6 per cent, and "
            "that the count rose only because the number of applications almost doubled. "
            "Dropping the rate leaves a summary that tells the reader refusals became more "
            "likely in the year they became less likely. Every word of it is true and the "
            "story is reversed."
        ),
    ),
    Edit(
        scenario_id="sum-28-kellet-branch",
        family="unsupported-claim",
        old="reopening delayed indefinitely pending signalling commissioning",
        new="reopens in September once signalling commissioning finishes",
        owner_reason=(
            "The passage says the reopening was announced for May, slipped first to "
            "September, and NOW HAS NO CONFIRMED DATE. The summary asserts a September "
            "reopening — a date the source explicitly withdraws in the same sentence it "
            "mentions it."
        ),
    ),
)


class _Recorder(ModelProvider):
    """Delegates to the real provider and keeps what answered.

    The judge is given the model name it asked for; the ANSWERING model is
    what the ADR has to name, and only the provider's result knows it (ADR
    0159's defect 1 is the reason this is recorded per call rather than
    assumed from the flag).
    """

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


# ---------------------------------------------------------------------------
# Building the hard set
# ---------------------------------------------------------------------------


def _scenario_path(scenario_id: str) -> Path:
    for split in ("train", "validation", "holdout"):
        path = CORPUS / split / f"{scenario_id}.json"
        if path.is_file():
            return path
    raise SystemExit(f"{scenario_id}: not in the corpus")


def _reflect_state(scenario: Scenario) -> AEFState:
    for record in scenario.trace:
        if record.node_id == JUDGED_NODE:
            return record.input_state
    raise SystemExit(f"{scenario.id}: no {JUDGED_NODE!r} record in the trace")


def _final_state(scenario: Scenario) -> AEFState:
    last = scenario.trace[-1]
    return last.delta.apply(last.input_state)


def _with_summary(state: AEFState, summary: str) -> AEFState:
    memory = dict(state.working_memory)
    memory["summary"] = summary
    return state.model_copy(update={"working_memory": memory})


def _task_text(scenario_id: str) -> str:
    """The instructions the writer was given, verbatim from the cassette.

    Passed to `PairwiseRanker` unchanged rather than restated, so the judge
    chooses against the same text the writer saw.
    """
    payload = json.loads(_scenario_path(scenario_id).read_text())
    for call in payload.get("model_calls") or ():
        for message in call["request"]["messages"]:
            if message["role"] == "user":
                return str(message["content"])
    raise SystemExit(f"{scenario_id}: no recorded user message to use as the task")


def build() -> list[dict[str, Any]]:
    """The twelve cases, with every claim about them asserted rather than
    asserted-in-prose: the edit applies exactly once, both members of a pair
    are within the cap, and the inherited checks are evaluated rather than
    predicted."""
    cases: list[dict[str, Any]] = []
    for edit in EDITS:
        scenario = load_scenario(_scenario_path(edit.scenario_id))
        reflect = _reflect_state(scenario)
        correct = str(reflect.working_memory["summary"])
        occurrences = correct.count(edit.old)
        if occurrences != 1:
            raise SystemExit(
                f"{edit.scenario_id}: the edit's `old` span occurs {occurrences} time(s) in "
                f"the recorded summary; a 'one minimal edit' claim needs exactly one"
            )
        corrupt = correct.replace(edit.old, edit.new)
        cap = int(reflect.working_memory["max_words"])
        for variant, summary, owner_pass in (
            ("correct", correct, True),
            ("corrupt", corrupt, False),
        ):
            words = len(summary.split())
            if words > cap:
                raise SystemExit(
                    f"{edit.scenario_id}/{variant}: {words} words against a cap of {cap}. "
                    f"Every case in the hard set must be WITHIN its cap, or a word counter "
                    f"discriminates and the set is ADR 0171's again."
                )
            report = evaluate_checks(
                scenario.checks, _with_summary(_final_state(scenario), summary)
            )
            cases.append(
                {
                    "case_id": f"{edit.scenario_id}:{variant}",
                    "scenario_id": edit.scenario_id,
                    "split": str(scenario.split),
                    "family": edit.family,
                    "variant": variant,
                    "owner_pass": owner_pass,
                    "owner_reason": (
                        "The agent's own recorded summary, verbatim from the cassette; it "
                        "answers the passage and passes every check the owner wrote for it."
                        if variant == "correct"
                        else edit.owner_reason
                    ),
                    "summary": summary,
                    "words": words,
                    "cap": cap,
                    "edit_old": edit.old if variant == "corrupt" else None,
                    "edit_new": edit.new if variant == "corrupt" else None,
                    "inherited_checks_passed": report.passed,
                    "inherited_checks_total": report.total,
                    "inherited_pass": report.passed == report.total,
                    "inherited_failures": list(report.failures),
                }
            )
    return sorted(cases, key=lambda c: str(c["case_id"]))


def write_hardset() -> None:
    cases = build()
    HARDSET.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {HARDSET.relative_to(REPO_ROOT)} — {len(cases)} case(s)\n")
    print(
        f"{'case':38s} {'fam':19s} {'own':4s} {'chk':7s} {'words/cap':>10s}",
    )
    for case in cases:
        print(
            f"{case['case_id']:38s} {case['family']:19s} "
            f"{'PASS' if case['owner_pass'] else 'FAIL':4s} "
            f"{str(case['inherited_checks_passed']) + '/' + str(case['inherited_checks_total']):7s} "
            f"{str(case['words']) + '/' + str(case['cap']):>10s}"
        )
    owner_fail = sum(1 for c in cases if not c["owner_pass"])
    over_cap = sum(1 for c in cases if c["words"] > c["cap"])
    print(
        f"\n{len(cases)} cases, {owner_fail} owner-fail, {over_cap} over cap "
        f"(a word-count judge therefore passes all {len(cases)})"
    )


def load_hardset() -> list[dict[str, Any]]:
    if not HARDSET.is_file():
        raise SystemExit(f"no hard set at {HARDSET}; run --build first")
    payload: list[dict[str, Any]] = json.loads(HARDSET.read_text())
    return payload


def _judged_state(case: dict[str, Any]) -> AEFState:
    scenario = load_scenario(_scenario_path(str(case["scenario_id"])))
    return _with_summary(_reflect_state(scenario), str(case["summary"]))


# ---------------------------------------------------------------------------
# The live arms
# ---------------------------------------------------------------------------


def _done_keys(path: Path, key: str) -> set[str]:
    if not path.is_file():
        return set()
    return {str(json.loads(line)[key]) for line in path.read_text().splitlines() if line.strip()}


def live_grade(judge_name: str, *, start: int, size: int) -> int:
    model = JUDGES[judge_name]
    cases = load_hardset()
    done = _done_keys(GRADES, "row_key")
    provider = _Recorder(ClaudeCodeProvider(default_model=model or None))
    judge = LLMJudge(provider=provider, model=model, rubric=RUBRIC, position_swap=True)
    made = 0
    for case in cases[start : start + size]:
        row_key = f"{judge_name}:{case['case_id']}"
        if row_key in done:
            print(f"skip {row_key} (already recorded)")
            continue
        judgment = judge.judge(_judged_state(case))
        calls = provider.drain()
        made += len(calls)
        match = _DELTA_RE.search(judgment.rationale)
        row = {
            "row_key": row_key,
            "arm": f"llm-{judge_name}",
            "judge": judge_name,
            "declared_model": model,
            "case_id": case["case_id"],
            "owner_pass": case["owner_pass"],
            "score": judgment.score,
            "position_delta": float(match.group(1)) if match else None,
            "rationale": judgment.rationale,
            "calls": calls,
        }
        with GRADES.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"{row_key:48s} score {judgment.score:.4f}  "
            f"delta {row['position_delta']}  owner {'PASS' if case['owner_pass'] else 'FAIL'}"
        )
    return made


def live_choose(judge_name: str) -> int:
    """`PairwiseRanker` on an act that CHOOSES rather than measures.

    Both candidates were written by `claude-opus-5[1m]` (the corrupt one is
    that text with one span replaced), so the shipped guard REFUSES the Opus
    judge by default. `--guard-demo` shows that refusal; this function passes
    `allow_self_ranking=True` explicitly, which is what an owner would have to
    do, and the point of the disinterested arm is that it does not have to.
    """
    model = JUDGES[judge_name]
    cases = {str(c["case_id"]): c for c in load_hardset()}
    done = _done_keys(CHOICES, "row_key")
    provider = _Recorder(ClaudeCodeProvider(default_model=model or None))
    ranker = PairwiseRanker(
        provider=provider, model=model, position_swap=True, allow_self_ranking=True
    )
    made = 0
    for edit in EDITS:
        row_key = f"{judge_name}:{edit.scenario_id}"
        if row_key in done:
            print(f"skip {row_key} (already recorded)")
            continue
        correct = cases[f"{edit.scenario_id}:correct"]
        corrupt = cases[f"{edit.scenario_id}:corrupt"]
        writer = "claude-opus-5[1m]"
        ranking = ranker.rank(
            _task_text(edit.scenario_id),
            Candidate(label="correct", text=str(correct["summary"]), model=writer),
            Candidate(label="corrupt", text=str(corrupt["summary"]), model=writer),
        )
        calls = provider.drain()
        made += len(calls)
        row = {
            "row_key": row_key,
            "judge": judge_name,
            "declared_model": model,
            "scenario_id": edit.scenario_id,
            "family": edit.family,
            "winner": ranking.winner,
            "consistent": ranking.consistent,
            "verdicts": list(ranking.verdicts),
            "correct_chosen": ranking.winner == "correct",
            "rationale": ranking.rationale,
            "calls": calls,
        }
        with CHOICES.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{row_key:44s} winner {ranking.winner}  verdicts {ranking.verdicts}")
    return made


def guard_demo() -> int:
    """The shipped control, exercised on the choosing act, both ways round.

    Case 1 costs nothing: the judge model is DECLARED, so the guard fires
    before any call. Case 2 costs one call and is the repo's own default
    configuration (`model: ""`), where the answering model's name does not
    exist until it has answered — the class docstring says this and it is
    cheaper to show it than to assert it.
    """
    cases = {str(c["case_id"]): c for c in load_hardset()}
    edit = EDITS[0]
    correct = Candidate(
        label="correct",
        text=str(cases[f"{edit.scenario_id}:correct"]["summary"]),
        model="claude-opus-5[1m]",
    )
    corrupt = Candidate(
        label="corrupt",
        text=str(cases[f"{edit.scenario_id}:corrupt"]["summary"]),
        model="claude-opus-5[1m]",
    )
    task = _task_text(edit.scenario_id)
    out: dict[str, Any] = {"row_key": "guard-demo", "cases": []}
    made = 0

    provider = _Recorder(ClaudeCodeProvider(default_model="claude-opus-5"))
    declared = PairwiseRanker(provider=provider, model="claude-opus-5")
    try:
        declared.rank(task, correct, corrupt)
        result = "NO REFUSAL — the guard did not fire"
    except SelfRankingError as exc:
        result = f"SelfRankingError: {exc}"
    spent = len(provider.drain())
    made += spent
    out["cases"].append({"when": "declared model", "calls": spent, "result": result})
    print(f"declared model  calls={spent}  {result[:120]}")

    provider = _Recorder(ClaudeCodeProvider(default_model=None))
    empty = PairwiseRanker(provider=provider, model="")
    try:
        empty.rank(task, correct, corrupt)
        result = "NO REFUSAL — the guard did not fire"
    except SelfRankingError as exc:
        result = f"SelfRankingError: {exc}"
    spent = len(provider.drain())
    made += spent
    out["cases"].append({"when": "empty model (this repo's default)", "calls": spent, "result": result})
    print(f"empty model     calls={spent}  {result[:120]}")

    with CHOICES.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(out, ensure_ascii=False) + "\n")
    return made


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _auc(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """P(a random owner-pass case scores above a random owner-fail one), ties
    at 0.5. 0.5 is no separation; below 0.5 is separation the wrong way."""
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def _agreement(rows: dict[str, float], cases: list[dict[str, Any]], threshold: float) -> int:
    hits = 0
    for case in cases:
        score = rows.get(str(case["case_id"]))
        if score is None:
            continue
        if (score >= threshold) == bool(case["owner_pass"]):
            hits += 1
    return hits


def report() -> None:
    cases = load_hardset()
    n = len(cases)
    by_id = {str(c["case_id"]): c for c in cases}
    grades: dict[str, dict[str, float]] = {}
    deltas: dict[str, list[tuple[str, float]]] = {}
    answering: dict[str, dict[str, int]] = {}
    if GRADES.is_file():
        for line in GRADES.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            grades.setdefault(str(row["judge"]), {})[str(row["case_id"])] = float(row["score"])
            if row.get("position_delta") is not None:
                deltas.setdefault(str(row["judge"]), []).append(
                    (str(row["case_id"]), float(row["position_delta"]))
                )
            for call in row.get("calls") or ():
                bucket = answering.setdefault(str(row["judge"]), {})
                bucket[str(call["model"])] = bucket.get(str(call["model"]), 0) + 1

    rule = {
        str(c["case_id"]): RuleBasedJudge(rubric=RUBRIC).judge(_judged_state(c)).score
        for c in cases
    }

    print("I14b — a fair test for the judge (ADR 0202)\n")
    print(f"hard set: {n} cases, {sum(1 for c in cases if not c['owner_pass'])} owner-fail, "
          f"{len(EDITS)} matched pairs, {len({c['family'] for c in cases})} failure families")
    print(f"every case within its cap: {all(c['words'] <= c['cap'] for c in cases)}\n")

    print("TRIVIAL BASELINES on this set (agreement with the owner's labels)")
    pass_all = sum(1 for c in cases if c["owner_pass"])
    fail_all = n - pass_all
    wordcount = sum(1 for c in cases if (c["words"] <= c["cap"]) == bool(c["owner_pass"]))
    inherited = sum(1 for c in cases if bool(c["inherited_pass"]) == bool(c["owner_pass"]))
    print(f"  answer 'pass' to everything          {pass_all}/{n}")
    print(f"  answer 'fail' to everything          {fail_all}/{n}")
    print(f"  word count against the cap only      {wordcount}/{n}")
    print(f"  the corpus's own inherited checks    {inherited}/{n}")
    print(f"  rule-based judge (no model call)     {_agreement(rule, cases, 0.5)}/{n}"
          f"   scores {min(rule.values()):.3f}-{max(rule.values()):.3f}\n")

    print("THE ARMS")
    header = f"  {'arm':12s} {'agree':>7s} {'AUC':>7s} {'paired':>8s} {'maxdelta':>9s}  scores"
    print(header)
    for judge_name in ("opus", "sonnet"):
        rows = grades.get(judge_name)
        if not rows:
            print(f"  llm-{judge_name:8s} (no judgments recorded yet)")
            continue
        pos = [s for cid, s in rows.items() if by_id[cid]["owner_pass"]]
        neg = [s for cid, s in rows.items() if not by_id[cid]["owner_pass"]]
        auc = _auc(pos, neg)
        paired = sum(
            1
            for e in EDITS
            if f"{e.scenario_id}:correct" in rows
            and f"{e.scenario_id}:corrupt" in rows
            and rows[f"{e.scenario_id}:correct"] > rows[f"{e.scenario_id}:corrupt"]
        )
        pairs_seen = sum(
            1
            for e in EDITS
            if f"{e.scenario_id}:correct" in rows and f"{e.scenario_id}:corrupt" in rows
        )
        md = max((d for _, d in deltas.get(judge_name, [])), default=0.0)
        print(
            f"  llm-{judge_name:8s} {_agreement(rows, cases, 0.5):>4d}/{n:<2d} "
            f"{(f'{auc:.3f}' if auc is not None else '   -'):>7s} "
            f"{f'{paired}/{pairs_seen}':>8s} {md:>9.3f}  "
            f"{min(rows.values()):.3f}-{max(rows.values()):.3f}"
        )

    for judge_name in ("opus", "sonnet"):
        rows = grades.get(judge_name)
        if not rows:
            continue
        print(f"\nAGREEMENT BY THRESHOLD — llm-{judge_name}")
        print("  " + "  ".join(f"{t:.2f}:{_agreement(rows, cases, t)}/{n}" for t in
                               (0.25, 0.4, 0.5, 0.6, 0.75)))

    print("\nPER CASE")
    print(f"  {'case':38s} {'own':4s} {'chk':5s} {'rule':>6s} {'opus':>7s} {'sonnet':>7s}")
    for case in cases:
        cid = str(case["case_id"])
        o = grades.get("opus", {}).get(cid)
        s = grades.get("sonnet", {}).get(cid)
        print(
            f"  {cid:38s} {'PASS' if case['owner_pass'] else 'FAIL':4s} "
            f"{'pass' if case['inherited_pass'] else 'FAIL':5s} "
            f"{rule[cid]:>6.3f} "
            f"{(f'{o:.3f}' if o is not None else '-'):>7s} "
            f"{(f'{s:.3f}' if s is not None else '-'):>7s}"
        )

    if grades.get("opus") and grades.get("sonnet"):
        shared = sorted(set(grades["opus"]) & set(grades["sonnet"]))
        gap = [grades["opus"][c] - grades["sonnet"][c] for c in shared]
        own = [grades["opus"][c] - grades["sonnet"][c] for c in shared if by_id[c]["owner_pass"]]
        print("\nSELF-PREFERENCE ON THE GRADING PATH")
        print(
            f"  mean(opus - sonnet) over {len(shared)} shared cases: {sum(gap) / len(gap):+.4f}"
        )
        if own:
            print(
                f"  ... over the {len(own)} cases the Opus judge itself wrote (owner-pass): "
                f"{sum(own) / len(own):+.4f}"
            )

    if CHOICES.is_file():
        print("\nTHE CHOOSING PATH — PairwiseRanker over the six matched pairs")
        rows_by_judge: dict[str, list[dict[str, Any]]] = {}
        for line in CHOICES.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("row_key") == "guard-demo":
                for entry in row["cases"]:
                    print(f"  guard, {entry['when']:34s} calls={entry['calls']}  "
                          f"{str(entry['result'])[:60]}")
                continue
            rows_by_judge.setdefault(str(row["judge"]), []).append(row)
        for judge_name, rows in sorted(rows_by_judge.items()):
            chose = sum(1 for r in rows if r["correct_chosen"])
            inconsistent = sum(1 for r in rows if not r["consistent"])
            print(
                f"  {judge_name:8s} chose the correct summary {chose}/{len(rows)}; "
                f"position-inconsistent {inconsistent}/{len(rows)}"
            )
            for row in rows:
                print(f"      {row['scenario_id']:26s} {row['family']:19s} "
                      f"winner={row['winner']}  verdicts={row['verdicts']}")

    if answering:
        print("\nWHAT ANSWERED")
        for judge_name, counts in sorted(answering.items()):
            print(f"  llm-{judge_name}: " + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())))


def dry_run() -> None:
    cases = build()
    print("I14b — a fair test for the judge. DRY RUN; nothing here spends a call.\n")
    print(f"hard set     : {len(cases)} cases from {len(EDITS)} passages, matched pairs")
    print(f"owner-fail   : {sum(1 for c in cases if not c['owner_pass'])}")
    print(f"within cap   : {sum(1 for c in cases if c['words'] <= c['cap'])}/{len(cases)}")
    print(f"families     : {', '.join(sorted({e.family for e in EDITS}))}")
    print()
    print("calls:")
    print(f"  {len(cases) * 2:>3d}  llm-opus   grading, 2 position-swapped samples per case")
    print(f"  {len(cases) * 2:>3d}  llm-sonnet grading, same")
    print(f"  {len(EDITS) * 2:>3d}  llm-opus   choosing, 2 orders per pair")
    print(f"  {len(EDITS) * 2:>3d}  llm-sonnet choosing, same")
    print("    1  the guard demo on this repo's own `model: \"\"` default")
    print(f"  {len(cases) * 4 + len(EDITS) * 4 + 1:>3d}  TOTAL, plus 2 quota preflights\n")
    for case in cases:
        print(f"  {case['case_id']:38s} {'PASS' if case['owner_pass'] else 'FAIL'}  "
              f"{case['words']:>2d}/{case['cap']:<2d} words  {case['family']}")
        print(f"      {case['summary']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-grade", action="store_true")
    parser.add_argument("--live-choose", action="store_true")
    parser.add_argument("--guard-demo", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--judge", choices=sorted(JUDGES), default="opus")
    parser.add_argument("--batch-start", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)

    if args.build:
        write_hardset()
    elif args.dry_run:
        dry_run()
    elif args.live_grade:
        made = live_grade(args.judge, start=args.batch_start, size=args.batch_size)
        print(f"\n{made} live call(s) made")
    elif args.live_choose:
        made = live_choose(args.judge)
        print(f"\n{made} live call(s) made")
    elif args.guard_demo:
        made = guard_demo()
        print(f"\n{made} live call(s) made")
    elif args.report:
        report()
    else:
        parser.error("one of --build/--dry-run/--live-grade/--live-choose/--guard-demo/--report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
