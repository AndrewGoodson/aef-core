"""The screen (ADR 0201's method, ADR 0204 step 3): six candidate owner rules,
scored against answers that already exist, BEFORE a call is spent recording
the scenarios the rules will be applied to.

Each candidate is one sentence of the persona's own output contract turned
into a machine-checkable predicate, plus the precondition under which it
applies. Preconditions read `objectives.py`'s `facts`, which were written
before any answer existed; the predicates read the arm-B answers.

The point of screening is to spend a rule on a failure that RECURS rather
than on one that never fires. A rule with 0 failures teaches the loop
nothing; a rule with 10 of 10 may be a rule nobody would write.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from objectives import OBJECTIVES  # noqa: E402

Q = pathlib.Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1"
)

STATUS = re.compile(r"(?mi)^\s*(?:[*_`#>\s-]*)status(?:\*\*)?\s*[:=]\s*(pass|fail|blocked)\b")
PUB_ORDER_FIELDS = re.compile(
    r"last_updated|record_modified|lastchangedon|last_edited_date|EditDate|OBJECTID|objectid",
    re.I,
)
GRACE_NONZERO = re.compile(r"grace_days[^0-9\n]{0,24}([1-9]\d*)")


def _rule_status(o, a) -> tuple[bool, bool]:
    """Every answer: the output contract's `status: pass|fail|blocked`."""
    return True, bool(STATUS.search(a))


def _rule_data_loss(o, a) -> tuple[bool, bool]:
    """A stated count mismatch must be escalated with the words DATA LOSS."""
    return bool(o["facts"].get("count_mismatch")), "DATA LOSS" in a


def _rule_left_behind(o, a) -> tuple[bool, bool]:
    """`source_count - fetched_count`, as a number, when counts disagree."""
    applies = o["facts"].get("left_behind") is not None
    n = o["facts"].get("left_behind")
    return bool(applies), bool(applies) and (str(n) in a or f"{n:,}" in a)


def _rule_watermark(o, a) -> tuple[bool, bool]:
    """When a cursor is in question, a publication/modification-order field
    must be NAMED, not merely described."""
    applies = bool(
        o["facts"].get("proposes_event_date_cursor") or o["facts"].get("grace_days_in_question")
    )
    return applies, bool(PUB_ORDER_FIELDS.search(a))


def _rule_cap_signal(o, a) -> tuple[bool, bool]:
    """An ArcGIS-sourced question must name the provider's own cap signal."""
    return bool(o["facts"].get("arcgis")), "exceededTransferLimit" in a


def _rule_grace(o, a) -> tuple[bool, bool]:
    """A non-zero grace window, with the number, when the window is at issue."""
    return bool(o["facts"].get("grace_days_in_question")), bool(GRACE_NONZERO.search(a))


def _rule_four_counts(o, a) -> tuple[bool, bool]:
    """The output contract's four counts, all four named in one answer."""
    low = a.lower()
    return True, all(w in low for w in ("source", "fetched", "lake", "published"))


def _rule_two_runs(o, a) -> tuple[bool, bool]:
    """AGENTS.md: no schedule until TWO manual runs reconcile. The answer must
    say so in words a reader can check, not only imply it."""
    return True, bool(re.search(r"two manual|second manual|2 manual", a, re.I))


def _rule_next_step(o, a) -> tuple[bool, bool]:
    """The output contract closes on 'the next bounded step'."""
    return True, bool(re.search(r"(?mi)^\s*(?:[*_`#>\s-]*)next step", a))


def _rule_count_query(o, a) -> tuple[bool, bool]:
    """The authoritative count query, named, on an ArcGIS question."""
    return bool(o["facts"].get("arcgis")), "returnCountOnly" in a


def _expected_status(o) -> str:
    """The verdict marlin's own rules force, computed from the objective's
    stated facts — one function, never a value typed per answer.

    The precedence is quoted from `.claude/agents/source-agent.md` and
    `AGENTS.md`, in this order, and each branch names the sentence it comes
    from:

    1. a stated count mismatch — "Any mismatch is `DATA LOSS` and a hard
       fail" -> `fail`;
    2. an unproven cap (a full page at or beyond the configured page size) —
       "Never infer completion from an absent next page; stop and fail until
       the source is proven exhausted" -> `fail`;
    3. a zero or absent grace window on a proposal to enable — "Require a
       non-zero, source-justified `grace_days`" -> `fail`;
    4. no authoritative count endpoint — "record the documented limitation
       and remain `blocked` unless an independent source-count artifact is
       supplied" -> `blocked`;
    5. a missing or event-date publication cursor — "Treat a missing
       publication-order cursor or unscoped connector as `blocked`" ->
       `blocked`;
    6. one manual run only, or no run evidence at all — AGENTS.md's "two
       manual runs ... and live readback passes" -> `blocked`;
    7. otherwise -> `pass`.

    NOTE, because it is the weakness of this rule and not a detail: on these
    ten questions branch 7 is never reached. Marlin's rules refuse all ten,
    six as `blocked` and four as `fail`. That is a property of what this agent
    IS — a gate whose job is mostly to say no — but it means the rule cannot
    catch an over-refusing agent. What stops it being degenerate is that the
    forced token is per scenario: an agent answering `blocked` to everything
    fails four, and one answering `fail` to everything fails six.
    """
    f = o["facts"]
    if f.get("count_mismatch"):
        return "fail"
    if f.get("full_page_at_cap"):
        return "fail"
    if f.get("zero_grace"):
        return "fail"
    if not f.get("authoritative_count_available"):
        return "blocked"
    if f.get("proposes_event_date_cursor"):
        return "blocked"
    if f.get("one_run_only") or f.get("no_run_evidence"):
        return "blocked"
    return "pass"


def _rule_verdict_token(o, a) -> tuple[bool, bool]:
    """The verdict token itself, against the one marlin's rules force."""
    m = STATUS.search(a)
    return True, bool(m) and m.group(1).lower() == _expected_status(o)


CANDIDATES = (
    ("R1  status: pass|fail|blocked line", _rule_status),
    ("R2  DATA LOSS on a count mismatch", _rule_data_loss),
    ("R3  the count left behind, as a number", _rule_left_behind),
    ("R4  a publication-order field named", _rule_watermark),
    ("R5  exceededTransferLimit named", _rule_cap_signal),
    ("R6  a non-zero grace_days, with the number", _rule_grace),
    ("R7  all four counts named", _rule_four_counts),
    ("R8  the two-manual-runs rule stated", _rule_two_runs),
    ("R9  a 'Next step' heading", _rule_next_step),
    ("R10 returnCountOnly named (ArcGIS)", _rule_count_query),
    ("R11 the verdict token marlin's rules force", _rule_verdict_token),
)


def answers(runs: pathlib.Path) -> list[tuple[str, str]]:
    """(objective id, answer) — matched by the objective text the run carries."""
    by_text = {o["text"]: o["id"] for o in OBJECTIVES}
    out = []
    for p in sorted(runs.glob("*.json")):
        d = json.loads(p.read_text())
        obj = d["initial_state"]["objective"]
        oid = next((v for k, v in by_text.items() if k in obj), None)
        assert oid is not None, f"run {p.name} carries an objective not in objectives.py"
        pa = next(t for t in d["trace"] if t["node_id"] == "prompt_agent")
        out.append((oid, pa["delta"]["working_memory"].get("prompt_agent", "")))
    return sorted(out)


def main() -> int:
    runs = Q / "runs-armB"
    rows = answers(runs)
    facts = {o["id"]: o for o in OBJECTIVES}
    print(f"screened against {len(rows)} arm-B answers in {runs.name}\n")
    print(f"{'candidate':44s} {'applies':>8s} {'fails':>6s} {'rate':>6s}")
    table = {}
    for name, fn in CANDIDATES:
        applies = fails = 0
        failed_ids = []
        for oid, a in rows:
            ap, ok = fn(facts[oid], a)
            if ap:
                applies += 1
                if not ok:
                    fails += 1
                    failed_ids.append(oid)
        rate = f"{(100 * fails / applies) if applies else 0:.0f}%"
        print(f"{name:44s} {applies:8d} {fails:6d} {rate:>6s}")
        table[name] = (applies, fails, failed_ids)
    print()
    for name, (_applies, fails, ids) in table.items():
        if fails:
            print(f"{name}\n    fails on: {', '.join(ids)}")
    payload = {k: {"applies": v[0], "fails": v[1], "ids": v[2]} for k, v in table.items()}
    (Q / "art" / "05-screen.json").write_text(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
