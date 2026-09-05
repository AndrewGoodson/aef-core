#!/usr/bin/env python
"""J4 rig A — the self-preference control (ADR 0162).

ADR 0171 closed dimension 3 at 7/10 with one gap named: *"the self-preference
control is untouched (S6's)"*. It was untouched because nothing in this repo
has a judge ranking MODEL OUTPUTS against each other — `LLMJudge` grades one
state at a time, and a judge that never sees two candidates cannot prefer its
own. This script is the first place it can.

Two summaries of the same passage, under the same instructions:

- **A-written** — the summary already in the cassette, verbatim, recorded from
  `claude-opus-5[1m]` (ADR 0171 recorded the whole corpus on it).
- **B-written** — the SAME recorded request, byte-identical system and user
  messages (asserted before the call), replayed through
  `ClaudeCodeProvider(default_model="claude-haiku-4-5-20251001")`.

Both judges — the same two models — then rank each pair, twice, with the
candidates in opposite positions. **Neither judge is told anything about
authorship**: the prompt this file builds contains no model name, and that is
a property of the committed prompt rather than a claim about intent.

The statistic is a difference of differences, because an absolute preference
rate confounds "this judge likes its own writing" with "one model simply wrote
better summaries":

    self_pref = P(judge A prefers the A-written summary)
              - P(judge B prefers the A-written summary)

A judge that merely recognises the better summary contributes equally to both
terms. Only a judge favouring its own model's text moves the difference. It is
reported beside the owner's checks, which score both candidates independently
and give the comparison a ground truth to be right or wrong about.

A third judge — `claude-sonnet-5`, which wrote NEITHER candidate — was added
after the first two arms measured an effect, and is what turns a symmetric
difference-of-differences into a per-judge number. See prereg.txt, amendment 2.

Pre-registered in `docs/research/j4/prereg.txt` before any call: the states,
the selection rule, the preference definition, the 0.20 threshold, and what
counts as +0. Amendment 1 cut the selection from 12 to the 11 Opus-recorded
validation scenarios, because six of the corpus's states are
`claude-fable-5-1` recordings and a self-preference control cannot use one.

Usage:

    python docs/research/j4/run_j4_selfpref.py --dry-run
    python docs/research/j4/run_j4_selfpref.py --write-candidates
    python docs/research/j4/run_j4_selfpref.py --rank --judge opus|haiku|sonnet
    python docs/research/j4/run_j4_selfpref.py --report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.harness.checks import evaluate_checks  # noqa: E402
from aef.harness.corpus import Scenario, load_scenario  # noqa: E402
from aef.providers.base import CompletionRequest, ProviderMessage  # noqa: E402
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402
from aef.reasoning.llm_reflection import (  # noqa: E402
    RANKER_SYSTEM,
    Candidate,
    PairwiseRanker,
    _parse_choice,
)
from aef.state import AEFState  # noqa: E402

HERE = Path(__file__).resolve().parent
CANDIDATES = HERE / "candidates.jsonl"
RANKINGS = HERE / "rankings.jsonl"

# The two models, named once. "" means: issue no --model flag, so the harness
# session's own default answers — the convention ADR 0171 recorded the corpus
# under, and the only way to be sure the judge is the model that wrote it.
MODEL_A = ""  # claude-opus-5[1m], asserted from the CLI's own modelUsage
MODEL_A_NAME = "claude-opus-5[1m]"
MODEL_B = "claude-haiku-4-5-20251001"
# The DISINTERESTED judge, added after the first two arms measured an effect:
# it wrote NEITHER candidate, so its preference rate is the reference both
# self-interested rates are read against. `sonnet` is the CLI's own alias; the
# name below is what `modelUsage` reported for it in `preflight-sonnet.json`.
MODEL_C = "sonnet"
MODEL_C_NAME = "claude-sonnet-5"
WRITERS = ("A", "B")
JUDGES = ("opus", "haiku", "sonnet")
JUDGE_MODEL = {"opus": MODEL_A, "haiku": MODEL_B, "sonnet": MODEL_C}
# Which writer each judge is the same model as. The disinterested judge is not
# in this map, and that is the point of it.
JUDGE_SELF = {"opus": "A", "haiku": "B"}

# Every Opus-recorded validation scenario — sum-29..sum-39, which is all of
# them except the six the corpus was born with. Those six (sum-13..sum-18)
# were recorded on `claude-fable-5-1`, and `--dry-run` prints the answering
# model per pair so a reader sees that rather than taking it on trust. A
# Fable-written summary cannot serve in a self-preference control: the Opus
# judge would not be looking at its own output, which is the entire variable.
# See prereg.txt, amendment 1. All four owner-check negatives are here.
SELECTED: tuple[str, ...] = (
    "sum-29-brindle-viaduct",
    "sum-30-ganister-tarn",
    "sum-31-quernmore-kiln",
    "sum-32-hessle-mills",
    "sum-33-cotterdale-bus",
    "sum-34-alder-carr",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
    "sum-37-ryhope-pool",
    "sum-38-bewick-refusals",
    "sum-39-coldbeck-society",
)

# The prompt and the parser are the SHIPPED ones (`aef.reasoning.llm_reflection`),
# not copies. The 66 judgments committed here were issued by this file's own
# inline versions; `PairwiseRanker` was then written against them and the two
# renderings were proved byte-identical before the local copies were deleted —
# sha256 of the system prompt
# 9a04e625894a066c7c7aa3f02791935ed559b19973ebd1df07143f9693501efb and of the
# sum-29 user turn d8607c653c6a81bf8c3530542293335b2927a8abbe206176a46ed8a842be0bad,
# pinned in tests/reasoning/test_pairwise_ranker.py so they cannot drift apart
# afterwards. `_parse_choice` is imported private on purpose: the committed data
# and the shipped code must not be able to disagree about what a reply means.
RANK_SYSTEM = RANKER_SYSTEM
# `allow_self_ranking=True` because two of the three arms ARE self-ranking —
# that is the measurement. The shipped default refuses them, which is the
# finding this rig produced (ADR 0162).
_PROMPTER = PairwiseRanker(
    provider=None,  # type: ignore[arg-type]  # prompt building only; never called
    model="",
    allow_self_ranking=True,
)


@dataclass(frozen=True)
class Pair:
    scenario: Scenario
    system: str
    user: str  # the recorded draft request, verbatim
    a_text: str  # the cassette's summary (written by MODEL_A)
    a_model: str  # what the cassette says answered


def _final_state(scenario: Scenario) -> AEFState:
    last = scenario.trace[-1]
    return last.delta.apply(last.input_state)


def _with_summary(scenario: Scenario, summary: str) -> AEFState:
    """The recorded final state with the summary swapped out, so both
    candidates are scored by the same checks against the same shape of state."""
    state = _final_state(scenario)
    memory = dict(state.working_memory)
    memory["summary"] = summary
    return state.model_copy(update={"working_memory": memory})


def load_pairs(corpus_root: Path) -> list[Pair]:
    pairs: list[Pair] = []
    for scenario_id in SELECTED:
        path = corpus_root / "validation" / f"{scenario_id}.json"
        scenario = load_scenario(path)
        if len(scenario.model_calls) != 1:
            raise SystemExit(f"{scenario_id}: expected exactly one recorded model call")
        call = scenario.model_calls[0]
        if call.result.model != MODEL_A_NAME:
            # The guard that would have caught amendment 1 before it cost
            # anything: six of the corpus's states are `claude-fable-5-1`
            # recordings, and a self-preference control over one of those
            # measures nothing.
            raise SystemExit(
                f"{scenario_id}: recorded on {call.result.model!r}, not {MODEL_A_NAME!r}; "
                f"a self-preference control needs writer A to be one model"
            )
        messages = call.request.messages
        system = next(m.content for m in messages if m.role == "system")
        user = next(m.content for m in messages if m.role == "user")
        pairs.append(
            Pair(
                scenario=scenario,
                system=system,
                user=user,
                a_text=call.result.content.strip(),
                a_model=call.result.model,
            )
        )
    return pairs


# --------------------------------------------------------------------------
# candidates


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_candidates(pairs: Sequence[Pair], out: Path) -> int:
    """One call per pair: the recorded request, replayed on MODEL_B."""
    done = {str(row["id"]) for row in _read_jsonl(out)}
    provider = ClaudeCodeProvider(default_model=MODEL_B)
    calls = 0
    with out.open("a") as handle:
        for pair in pairs:
            if pair.scenario.id in done:
                print(f"skip {pair.scenario.id} (already in {out.name})")
                continue
            request = CompletionRequest(
                messages=(
                    ProviderMessage(role="system", content=pair.system),
                    ProviderMessage(role="user", content=pair.user),
                ),
                model="",  # the provider's default, i.e. MODEL_B
                max_tokens=16000,
            )
            started = time.monotonic()
            result = provider.complete(request)
            elapsed = time.monotonic() - started
            calls += 1
            row = {
                "id": pair.scenario.id,
                "writer": "B",
                "model_requested": MODEL_B,
                "model_answered": result.model,
                "text": result.content.strip(),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "stop_reason": result.stop_reason,
                "elapsed_s": round(elapsed, 2),
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            print(
                f"{pair.scenario.id}: {len(row['text'].split())} words "
                f"by {result.model} ({elapsed:.1f}s)"
            )
    return calls


# --------------------------------------------------------------------------
# ranking


def _rank_prompt(pair: Pair, first: str, second: str) -> str:
    """The judge's user turn, built by the shipped `PairwiseRanker`. The
    instructions are the ones both writers had — lifted from the recorded
    request rather than restated, so the judge grades against the same text the
    writers were given. The writer models are passed so that a future reader
    running this file gets the shipped guard's behaviour, not a copy of it."""
    return _PROMPTER.prompt(
        pair.user,
        Candidate(label="first", text=first, model=""),
        Candidate(label="second", text=second, model=""),
    )


def parse_verdict(text: str) -> str | None:
    """`"A"` or `"B"` from the reply, or `None`. Code owns the tally; the model
    supplies one label and nothing it says can add an outcome."""
    return _parse_choice(text)


def _candidate_b(rows: list[dict[str, Any]], scenario_id: str) -> str:
    for row in rows:
        if str(row["id"]) == scenario_id:
            return str(row["text"])
    raise SystemExit(f"{scenario_id}: no B candidate yet — run --write-candidates first")


def rank(pairs: Sequence[Pair], judge: str, out: Path, limit: int) -> int:
    """Two calls per pair for this judge: A first, then B first."""
    model = JUDGE_MODEL[judge]
    provider = ClaudeCodeProvider(default_model=model or None)
    candidates = _read_jsonl(CANDIDATES)
    done = {(str(r["id"]), str(r["judge"]), str(r["order"])) for r in _read_jsonl(out)}
    calls = 0
    with out.open("a") as handle:
        for pair in pairs:
            b_text = _candidate_b(candidates, pair.scenario.id)
            for order in ("A_first", "B_first"):
                if calls >= limit:
                    return calls
                key = (pair.scenario.id, judge, order)
                if key in done:
                    print(f"skip {key}")
                    continue
                first, second = (
                    (pair.a_text, b_text) if order == "A_first" else (b_text, pair.a_text)
                )
                request = CompletionRequest(
                    messages=(
                        ProviderMessage(role="system", content=RANK_SYSTEM),
                        ProviderMessage(role="user", content=_rank_prompt(pair, first, second)),
                    ),
                    model="",
                    max_tokens=200,
                )
                started = time.monotonic()
                result = provider.complete(request)
                elapsed = time.monotonic() - started
                calls += 1
                label = parse_verdict(result.content)
                # Position -> writer. In A_first, label "A" is the A-written
                # candidate; in B_first it is the B-written one.
                preferred = None
                if label is not None:
                    if order == "A_first":
                        preferred = "A" if label == "A" else "B"
                    else:
                        preferred = "B" if label == "A" else "A"
                row = {
                    "id": pair.scenario.id,
                    "judge": judge,
                    "judge_model_requested": model or "(session default)",
                    "judge_model_answered": result.model,
                    "order": order,
                    "label": label,
                    "preferred_writer": preferred,
                    "raw": result.content.strip()[:400],
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "stop_reason": result.stop_reason,
                    "elapsed_s": round(elapsed, 2),
                }
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                print(
                    f"{pair.scenario.id} {judge} {order}: label={label} "
                    f"prefers={preferred} by {result.model} ({elapsed:.1f}s)"
                )
    return calls


# --------------------------------------------------------------------------
# report


def _owner_scores(pair: Pair, b_text: str) -> tuple[float, float]:
    a = evaluate_checks(pair.scenario.checks, _with_summary(pair.scenario, pair.a_text)).fraction
    b = evaluate_checks(pair.scenario.checks, _with_summary(pair.scenario, b_text)).fraction
    return a, b


def _preference(rows: list[dict[str, Any]], scenario_id: str, judge: str) -> str:
    """A judge's preference on one pair: 'A', 'B', 'inconsistent' (the two
    orders disagreed — the position control), or 'incomplete'."""
    seen = {
        str(r["order"]): r.get("preferred_writer")
        for r in rows
        if str(r["id"]) == scenario_id and str(r["judge"]) == judge
    }
    if len(seen) < 2 or any(v is None for v in seen.values()):
        return "incomplete"
    values = set(seen.values())
    return next(iter(values)) if len(values) == 1 else "inconsistent"


def report(corpus_root: Path) -> None:
    pairs = load_pairs(corpus_root)
    candidates = _read_jsonl(CANDIDATES)
    rankings = _read_jsonl(RANKINGS)
    judges = tuple(j for j in JUDGES if any(str(r["judge"]) == j for r in rankings))

    answered = {}
    for judge in judges:
        answered[judge] = sorted(
            {str(r["judge_model_answered"]) for r in rankings if str(r["judge"]) == judge}
        )
    print(f"writer A = {MODEL_A_NAME} (from the cassette); writer B = {MODEL_B}")
    print(f"B candidates answered by: {sorted({str(r['model_answered']) for r in candidates})}")
    for judge in judges:
        print(f"judge {judge:<6} answered by: {answered[judge]}")
    total_calls = len(candidates) + len(rankings)
    print(
        f"{total_calls} live calls in the committed data ({len(candidates)} write, "
        f"{len(rankings)} rank)"
    )
    print()

    header = f"{'id':<24}{'checks A':>9}{'checks B':>9}{'favour':>8}" + "".join(
        f"{j:>14}" for j in judges
    )
    print(header)
    print("-" * len(header))
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        b_text = _candidate_b(candidates, pair.scenario.id)
        a_score, b_score = _owner_scores(pair, b_text)
        favour = "A" if a_score > b_score else "B" if b_score > a_score else "tie"
        prefs = {j: _preference(rankings, pair.scenario.id, j) for j in judges}
        rows.append(
            {
                "id": pair.scenario.id,
                "a_score": a_score,
                "b_score": b_score,
                "favour": favour,
                **{f"pref_{j}": prefs[j] for j in judges},
            }
        )
        print(
            f"{pair.scenario.id:<24}{a_score:>9.2f}{b_score:>9.2f}{favour:>8}"
            + "".join(f"{prefs[j]:>14}" for j in judges)
        )
    print()

    print("2x2 — judge x preferred writer (rows sum to the consistent pairs):")
    print(
        f"{'judge':<9}{'self':>6}{'prefers A':>11}{'prefers B':>11}"
        f"{'inconsistent':>14}{'incomplete':>12}"
    )
    rates: dict[str, float] = {}
    for judge in judges:
        counts = {
            k: sum(1 for r in rows if r[f"pref_{judge}"] == k)
            for k in ("A", "B", "inconsistent", "incomplete")
        }
        consistent = counts["A"] + counts["B"]
        rates[judge] = counts["A"] / consistent if consistent else float("nan")
        print(
            f"{judge:<9}{JUDGE_SELF.get(judge, '-'):>6}{counts['A']:>11}{counts['B']:>11}"
            f"{counts['inconsistent']:>14}{counts['incomplete']:>12}"
        )
    print()
    print("P(prefers the A-written summary), over that judge's consistent pairs:")
    for judge in judges:
        print(f"  judge {judge:<7} {rates[judge]:.3f}")
    if "opus" in rates and "haiku" in rates:
        self_pref = rates["opus"] - rates["haiku"]
        print(
            "  difference-in-differences, the two self-interested judges only:\n"
            f"    P(opus prefers A) - P(haiku prefers A) = {self_pref:+.3f}"
        )
    if "sonnet" in rates:
        # The disinterested judge wrote neither candidate, so its rate is what
        # each self-interested rate is a deviation FROM. This turns a symmetric
        # difference-of-differences — which can only say the two judges differ —
        # into a per-judge number that says which one is biased and by how much.
        print(
            "  against the disinterested judge (wrote neither candidate):\n"
            f"    opus  self-preference = P(opus prefers A)  - P(sonnet prefers A)  "
            f"= {rates['opus'] - rates['sonnet']:+.3f}\n"
            f"    haiku self-preference = P(sonnet prefers A) - P(haiku prefers A)  "
            f"= {rates['sonnet'] - rates['haiku']:+.3f}"
        )
    print()

    discriminating = [r for r in rows if r["favour"] != "tie"]
    print(
        f"agreement with the owner checks, on the {len(discriminating)} pair(s) where the "
        f"checks discriminate:"
    )
    agree: dict[str, float] = {}
    for judge in judges:
        usable = [r for r in discriminating if r[f"pref_{judge}"] in WRITERS]
        hits = sum(1 for r in usable if r[f"pref_{judge}"] == r["favour"])
        agree[judge] = hits / len(usable) if usable else float("nan")
        print(f"  judge {judge:<7} {hits}/{len(usable)} = {agree[judge]:.3f}")
    if "opus" in agree and "haiku" in agree:
        print(f"  |opus - haiku| = {abs(agree['opus'] - agree['haiku']):.3f}")
    print()
    print("position control — pairs where the two orders disagreed:")
    for judge in judges:
        n_inc = sum(1 for r in rows if r[f"pref_{judge}"] == "inconsistent")
        print(f"  judge {judge:<7} {n_inc}/{len(rows)}")


def dry_run(corpus_root: Path) -> None:
    pairs = load_pairs(corpus_root)
    print(
        f"{len(pairs)} pairs; {len(pairs)} write calls + {len(pairs) * 4} rank calls "
        f"= {len(pairs) * 5} live calls"
    )
    print(f"{'id':<24}{'cap':>5}{'A words':>9}{'A model':>22}")
    for pair in pairs:
        cap = pair.scenario.initial_state.working_memory.get("max_words")
        print(f"{pair.scenario.id:<24}{str(cap):>5}{len(pair.a_text.split()):>9}{pair.a_model:>22}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-candidates", action="store_true")
    mode.add_argument("--rank", action="store_true")
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--judge", choices=JUDGES)
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "corpus")
    parser.add_argument("--batch-size", type=int, default=8, help="max live calls this run")
    args = parser.parse_args(argv)

    if args.report:
        report(args.corpus)
        return 0
    if args.dry_run:
        dry_run(args.corpus)
        return 0

    pairs = load_pairs(args.corpus)
    if args.write_candidates:
        calls = write_candidates(pairs, CANDIDATES)
    else:
        if args.judge is None:
            parser.error("--rank needs --judge " + "|".join(JUDGES))
        calls = rank(pairs, args.judge, RANKINGS, args.batch_size)
    print(f"calls made this invocation: {calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
