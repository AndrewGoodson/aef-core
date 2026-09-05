#!/usr/bin/env python
"""J4 rig B — is a lesson ever harmful AND resolved? (ADR 0162)

ADR 0118 surfaced `helpful`/`harmful` tallies on a `KnowledgeEntry` and
deliberately did not rank on them, because on every rig built so far the two
signals coincide: `_tally` in `aef/services/knowledge/consolidate.py` calls a
run **harmful** when it had the lesson in context and *reproduced that same
failure*, so "harmful" and "still live" are the same fact and demoting a
harmful lesson would be demoting exactly the lesson worth showing.

BEYOND_90's J4 asks for the corpus that pulls them apart: a lesson that is
retrieved and makes a later run fail **differently**. This script tries to
build it, honestly, and reports what happened either way.

The lesson is not written by hand. The corpus's seven owner-check negatives
are all `max_words` overruns (ADR 0171). This script turns each into one
`MemoryRecord` whose verbal feedback comes from the REAL `RuleBasedCritic`
over a derived state carrying that check failure as `state.errors[0]` — ADR
0157's method, because the harness producer that would do this in a run (M4b,
ADR 0174) is on a branch that has not landed on `main` and this worker may not
depend on it. Synthetic in origin, real in shape, and the signature is ADR
0174's own (`failure:check:<path>:<op>`), so the rig is not building a
different object from the one the repo will have. The shipped
`RuleBasedConsolidator` then folds the seven into one entry, and the shipped
`MemoryRetriever` + `render_retrieved_context` put it in the prompt.

Two arms, both on `claude-opus-5[1m]` — the model that recorded every baseline
used here (six of the corpus's twenty were recorded on `claude-fable-5-1` and
are excluded for that reason):

- **harm probes** — five scenarios that PASS every owner check in the baseline
  and whose recorded summary is at or within two words of the cap. If the
  lesson makes one of them drop a `must_mention` term, that is a lesson that
  is harmful and resolved.
- **help probes** — cap negatives re-run with the same lesson, to say whether
  it buys anything where it does apply.

Usage:

    python docs/research/j4/run_j4_harm.py --dry-run
    python docs/research/j4/run_j4_harm.py --live --arm harm
    python docs/research/j4/run_j4_harm.py --live --arm help
    python docs/research/j4/run_j4_harm.py --report
    python docs/research/j4/run_j4_harm.py --tally

`--tally` is the one that decides dimension 2: it writes the ten runs back as
the `MemoryRecord`s a real reflect+consolidate pass would have written and lets
the SHIPPED consolidator compute `helpful`/`harmful`, so what the repo's own
tally makes of a harmful lesson is run rather than reasoned about.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.harness.checks import evaluate_checks  # noqa: E402
from aef.harness.corpus import Scenario, load_scenario  # noqa: E402
from aef.providers.base import CompletionRequest, ProviderMessage  # noqa: E402
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402
from aef.reasoning.nodes import render_retrieved_context  # noqa: E402
from aef.reasoning.rule_based_reflection import RuleBasedCritic  # noqa: E402
from aef.services.context.memory_retriever import MemoryRetriever  # noqa: E402
from aef.services.knowledge.consolidate import RuleBasedConsolidator  # noqa: E402
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore  # noqa: E402
from aef.services.memory.base import MemoryRecord  # noqa: E402
from aef.services.memory.in_memory import InMemoryMemoryStore  # noqa: E402
from aef.state import AEFState  # noqa: E402
from agents.summary.graph import SYSTEM_PROMPT, draft_prompt  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "harm.jsonl"
AGENT_ID = "summary_agent"

# The seven owner-check negatives (ADR 0171). Every one is a max_words overrun,
# which is what makes ONE lesson out of seven runs rather than seven lessons.
NEGATIVES: tuple[tuple[str, str], ...] = (
    ("train", "sum-22-marlowe-street"),
    ("train", "sum-25-hollin-bridge"),
    ("train", "sum-26-netherby-clinic"),
    ("validation", "sum-30-ganister-tarn"),
    ("validation", "sum-33-cotterdale-bus"),
    ("validation", "sum-35-priory-gatehouse"),
    ("validation", "sum-36-larkfield-quarry"),
)

# Pre-registered (prereg.txt, amendment 1). Opus recordings only; owner-PASS in
# the baseline; recorded summary at or within two words of the cap; multi-word
# must_mention terms, so "be shorter" has something to cut out.
HARM_PROBES: tuple[tuple[str, str], ...] = (
    ("train", "sum-24-pellow-mill"),
    ("train", "sum-23-cransley-cut"),
    ("validation", "sum-31-quernmore-kiln"),
    ("validation", "sum-34-alder-carr"),
    ("validation", "sum-39-coldbeck-society"),
)

HELP_PROBES: tuple[tuple[str, str], ...] = (
    ("train", "sum-22-marlowe-street"),
    ("validation", "sum-30-ganister-tarn"),
    ("validation", "sum-33-cotterdale-bus"),
    ("validation", "sum-35-priory-gatehouse"),
    ("validation", "sum-36-larkfield-quarry"),
)


def check_signature(record: MemoryRecord) -> str | None:
    """ADR 0174's key: the failed check's identity WITHOUT its expected value.

    `failing_nodes` is empty on these records by construction — no node failed,
    the run answered cleanly and missed the owner's metric — so
    `default_signature` cannot sign them at all. The value is dropped from the
    key on ADR 0174's reasoning: it is what lets the same check failing on two
    different inputs recur, and it keeps a target string out of a marker that
    gets rendered into a prompt.
    """
    if record.kind != "failure":
        return None
    failed = record.content.get("failed_checks")
    if not isinstance(failed, (list, tuple)) or not failed:
        return None
    first = failed[0]
    if not isinstance(first, dict):
        return None
    path, op = first.get("path"), first.get("op")
    if not isinstance(path, str) or not isinstance(op, str):
        return None
    return f"failure:check:{path}:{op}"


def _load(split: str, scenario_id: str, corpus_root: Path) -> Scenario:
    return load_scenario(corpus_root / split / f"{scenario_id}.json")


def _final_state(scenario: Scenario) -> AEFState:
    last = scenario.trace[-1]
    return last.delta.apply(last.input_state)


def _with_summary(state: AEFState, summary: str) -> AEFState:
    memory = dict(state.working_memory)
    memory["summary"] = summary
    return state.model_copy(update={"working_memory": memory})


def _failed_checks(scenario: Scenario, state: AEFState) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for check in scenario.checks:
        one = evaluate_checks((check,), state)
        if one.passed == 0:
            out.append({"path": check.path, "op": check.op, "detail": one.failures[0]})
    return out


def build_lesson(corpus_root: Path) -> tuple[InMemoryMemoryStore, InMemoryKnowledgeStore, Any]:
    """Seven failure records -> one consolidated entry, through shipped code."""
    memory = InMemoryMemoryStore()
    critic = RuleBasedCritic()
    for split, scenario_id in NEGATIVES:
        scenario = _load(split, scenario_id, corpus_root)
        final = _final_state(scenario)
        failed = _failed_checks(scenario, final)
        if not failed:
            raise SystemExit(f"{scenario_id}: expected a failing owner check, found none")
        # The derived copy ADR 0174 argues for: the check failure is put where
        # the critic looks, WITHOUT touching the run's own recorded state (which
        # would move its score and flip classify()).
        derived = final.model_copy(
            update={
                "errors": [
                    {"node_id": "draft", "error": f["detail"], "message": f["detail"]}
                    for f in failed
                ]
            }
        )
        critique = critic.critique(derived)
        memory.write(
            MemoryRecord(
                kind="failure",
                content={
                    "verbal_feedback": critique.verbal_feedback,
                    "grounded_in": list(critique.grounded_in),
                    "failed_checks": failed,
                    "failing_nodes": [],
                    "retrieved_signatures": [],
                    "objective": scenario.initial_state.objective,
                    "node_id": "reflect",
                },
                run_id=scenario.id,
                agent_id=AGENT_ID,
                tags=("summary",),
                created_at=scenario.recorded_at,
            )
        )
    knowledge = InMemoryKnowledgeStore()
    entries = RuleBasedConsolidator(signature_fn=check_signature).consolidate(
        memory, knowledge, agent_id=AGENT_ID
    )
    if len(entries) != 1:
        raise SystemExit(f"expected one consolidated entry, got {len(entries)}")
    return memory, knowledge, entries[0]


def lesson_block(knowledge: InMemoryKnowledgeStore, state: AEFState) -> tuple[str, list[Any]]:
    """The bullet the shipped retriever + renderer produce for this state.

    `kinds=()` — the retriever reads the consolidated entry and NOT the seven
    raw records it was built from. Stated because it is a choice: with the raw
    records admitted, seven near-duplicate accounts of the same overrun would
    share the prompt with the lesson and no behaviour change could be
    attributed to the lesson rather than to the bulk.
    """
    retriever = MemoryRetriever(
        memory=InMemoryMemoryStore(),
        agent_id=AGENT_ID,
        kinds=(),
        knowledge=knowledge,
        knowledge_kinds=("failure",),
    )
    chunks = retriever.retrieve(state.objective, token_budget=state.context_budget_tokens)
    staged = state.model_copy(
        update={
            "retrieved_context": [
                {
                    "content": c.content,
                    "source": c.source,
                    "relevance_score": c.relevance_score,
                    "token_estimate": c.token_estimate,
                    "metadata": dict(c.metadata),
                }
                for c in chunks
            ]
        }
    )
    return render_retrieved_context(staged), list(chunks)


def _probe_rows(arm: str) -> tuple[tuple[str, str], ...]:
    return HARM_PROBES if arm == "harm" else HELP_PROBES


def _baseline(scenario: Scenario) -> tuple[str, int, int]:
    final = _final_state(scenario)
    summary = str(final.working_memory.get("summary", ""))
    report = evaluate_checks(scenario.checks, final)
    return summary, report.passed, report.total


def _read_done(out: Path) -> set[tuple[str, str]]:
    if not out.exists():
        return set()
    return {
        (str(json.loads(line)["id"]), str(json.loads(line)["arm"]))
        for line in out.read_text().splitlines()
        if line.strip()
    }


def run(arm: str, corpus_root: Path, *, live: bool) -> int:
    _, knowledge, entry = build_lesson(corpus_root)
    done = _read_done(OUT) if live else set()
    calls = 0
    handle = OUT.open("a") if live else None
    try:
        for split, scenario_id in _probe_rows(arm):
            scenario = _load(split, scenario_id, corpus_root)
            state = scenario.initial_state
            text = str(state.working_memory.get("text", ""))
            cap = int(state.working_memory.get("max_words", 40))
            terms = [str(t) for t in state.working_memory.get("must_mention", [])]
            block, chunks = lesson_block(knowledge, state)
            recorded_user = next(
                m.content for m in scenario.model_calls[0].request.messages if m.role == "user"
            )
            # The rig's own integrity check: with no lesson, the prompt this
            # script builds is the prompt the cassette recorded, byte for byte.
            # Without it, a behaviour change could be an artefact of rebuilding
            # the prompt rather than of the lesson.
            if draft_prompt(text, cap, terms, "") != recorded_user:
                raise SystemExit(
                    f"{scenario_id}: rebuilt baseline prompt differs from the cassette"
                )
            prompt = draft_prompt(text, cap, terms, block)
            base_summary, base_passed, base_total = _baseline(scenario)
            if not live:
                print(
                    f"{scenario_id:<26} cap={cap:<3} baseline {base_passed}/{base_total} "
                    f"{len(base_summary.split())}w  retrieved={len(chunks)} chunk(s) "
                    f"block={len(block)} chars"
                )
                continue
            if (scenario_id, arm) in done:
                print(f"skip {scenario_id} ({arm})")
                continue
            provider = ClaudeCodeProvider(default_model=None)
            started = time.monotonic()
            result = provider.complete(
                CompletionRequest(
                    messages=(
                        ProviderMessage(role="system", content=SYSTEM_PROMPT),
                        ProviderMessage(role="user", content=prompt),
                    ),
                    model="",
                    max_tokens=16000,
                )
            )
            elapsed = time.monotonic() - started
            calls += 1
            summary = result.content.strip()
            final = _with_summary(_final_state(scenario), summary)
            report = evaluate_checks(scenario.checks, final)
            base_failed = {
                f["path"] + " " + f["op"] for f in _failed_checks(scenario, _final_state(scenario))
            }
            now_failed = {f["path"] + " " + f["op"] for f in _failed_checks(scenario, final)}
            row = {
                "id": scenario.id,
                "arm": arm,
                "split": split,
                "cap": cap,
                "must_mention": terms,
                "lesson_signature": entry.signature,
                "lesson_occurrences": entry.occurrence_count,
                "lesson_block": block,
                "baseline_summary": base_summary,
                "baseline_words": len(base_summary.split()),
                "baseline_passed": base_passed,
                "baseline_total": base_total,
                "baseline_failed_checks": sorted(base_failed),
                "summary": summary,
                "words": len(summary.split()),
                "passed": report.passed,
                "total": report.total,
                "failed_checks": sorted(now_failed),
                "newly_failed": sorted(now_failed - base_failed),
                "newly_passed": sorted(base_failed - now_failed),
                "model_answered": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "stop_reason": result.stop_reason,
                "elapsed_s": round(elapsed, 2),
            }
            assert handle is not None
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            print(
                f"{scenario.id:<26} {base_passed}/{base_total} -> {report.passed}/{report.total} "
                f"{len(base_summary.split())}w -> {len(summary.split())}w "
                f"newly_failed={row['newly_failed']} newly_passed={row['newly_passed']}"
            )
    finally:
        if handle is not None:
            handle.close()
    return calls


def tally(corpus_root: Path) -> None:
    """What the SHIPPED consolidator makes of the ten runs this rig recorded.

    This is the question dimension 2 turns on, and it is answered by running
    the code rather than by reading it: each live run is written back as the
    `MemoryRecord` a real `reflect` + `consolidate` pass would have written —
    `retrieved_signatures` naming the lesson that was in context, the failed
    owner checks keyed ADR 0174's way — and `RuleBasedConsolidator` then
    computes `helpful`/`harmful` with its own `_tally`, untouched.
    """
    memory, knowledge, first_gen = build_lesson(corpus_root)
    rows = [json.loads(line) for line in OUT.read_text().splitlines() if line.strip()]
    print(
        f"first generation: {first_gen.signature} x{first_gen.occurrence_count}, "
        f"helpful/harmful {first_gen.helpful}/{first_gen.harmful} "
        f"(no run had it in context yet)"
    )
    print()
    header = f"{'run'.ljust(30)}{'own signature':<50}{'reproduced the lesson?':>23}"
    print(header)
    print("-" * len(header))
    for row in sorted(rows, key=lambda r: (str(r["arm"]), str(r["id"]))):
        scenario = _load(str(row["split"]), str(row["id"]), corpus_root)
        final = _with_summary(_final_state(scenario), str(row["summary"]))
        failed = _failed_checks(scenario, final)
        kind = "failure" if failed else "success"
        record = MemoryRecord(
            kind=kind,
            content={
                "verbal_feedback": "with-lesson run recorded by docs/research/j4/run_j4_harm.py",
                "grounded_in": [],
                "failed_checks": failed,
                "failing_nodes": [],
                # The lesson WAS in context: this is the field ADR 0118's
                # tally reads, written by `retrieved_signatures()` in a real run.
                "retrieved_signatures": [first_gen.signature],
                "objective": scenario.initial_state.objective,
                "node_id": "reflect",
            },
            run_id=f"{scenario.id}-with-lesson",
            agent_id=AGENT_ID,
            tags=("summary",),
            created_at=scenario.recorded_at,
        )
        memory.write(record)
        own = check_signature(record) or f"success:{scenario.initial_state.objective}"
        reproduced = own == first_gen.signature
        print(f"{str(row['id']).ljust(30)}{own:<50}{('yes' if reproduced else 'NO'):>23}")
    print()
    fresh = InMemoryKnowledgeStore()
    entries = RuleBasedConsolidator(signature_fn=check_signature).consolidate(
        memory, fresh, agent_id=AGENT_ID
    )
    for entry in entries:
        print(
            f"{entry.signature:<50} x{entry.occurrence_count:<3} "
            f"helpful={entry.helpful} harmful={entry.harmful}"
        )


def report(corpus_root: Path) -> None:
    memory, knowledge, entry = build_lesson(corpus_root)
    print("the consolidated lesson, from shipped code over seven recorded failures:")
    print(f"  signature        {entry.signature}")
    print(f"  occurrence_count {entry.occurrence_count}  (distinct runs)")
    print(f"  confidence       {entry.confidence}")
    print(f"  helpful/harmful  {entry.helpful}/{entry.harmful}")
    print(f"  runs_since_seen  {entry.runs_since_last_seen}")
    print(f"  text             {json.dumps(entry.content)[:300]}")
    print()
    rows = (
        [json.loads(line) for line in OUT.read_text().splitlines() if line.strip()]
        if OUT.exists()
        else []
    )
    if not rows:
        print("no live rows yet")
        return
    for arm in ("harm", "help"):
        subset = [r for r in rows if r["arm"] == arm]
        if not subset:
            continue
        print(
            f"--- {arm} probes, {len(subset)} run(s), model(s) "
            f"{sorted({r['model_answered'] for r in subset})} ---"
        )
        header = (
            f"{'id':<26}{'cap':>4}{'base w':>7}{'new w':>6}"
            f"{'base':>6}{'new':>6}  newly failed / newly passed"
        )
        print(header)
        print("-" * len(header))
        for r in sorted(subset, key=lambda r: str(r["id"])):
            print(
                f"{r['id']:<26}{r['cap']:>4}{r['baseline_words']:>7}{r['words']:>6}"
                f"{r['baseline_passed']}/{r['baseline_total']:<4}{r['passed']}/{r['total']:<4}  "
                f"{r['newly_failed']} / {r['newly_passed']}"
            )
        harmed = [r for r in subset if r["newly_failed"]]
        helped = [r for r in subset if r["newly_passed"]]
        print(f"  runs that failed a check they had passed: {len(harmed)}/{len(subset)}")
        print(f"  runs that passed a check they had failed: {len(helped)}/{len(subset)}")
        print()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--report", action="store_true")
    # `--verify` is the shared re-runner interface (ADR 0196): an alias of
    # `--report`, so `docs/research/measure.py` can invoke every runner the
    # same way. Re-derives the published table from the committed results
    # file; zero live calls.
    mode.add_argument("--verify", action="store_true", help="alias of --report (ADR 0196)")
    mode.add_argument("--tally", action="store_true")
    parser.add_argument("--arm", choices=("harm", "help"), default="harm")
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "corpus")
    args = parser.parse_args(argv)
    args.report = args.report or args.verify

    if args.report:
        report(args.corpus)
        return 0
    if args.tally:
        tally(args.corpus)
        return 0
    calls = run(args.arm, args.corpus, live=args.live)
    if args.live:
        print(f"calls made this invocation: {calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
