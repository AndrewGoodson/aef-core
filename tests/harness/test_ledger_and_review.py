"""Proposal ledger, review surface, and gate observability.

M9's acceptance properties. The ledger is the audit trail under tiered
auto-merge, so the test that matters is the tamper test: a system that can
merge its own changes could also, in principle, edit the record of having
done so.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aef.harness.corpus import Split
from aef.harness.gates.base import (
    Gate,
    GateContext,
    GateOutcome,
    GateResult,
    PipelineResult,
    run_pipeline,
)
from aef.harness.ledger import (
    EventKind,
    LedgerError,
    LedgerTamperedError,
    append,
    history_for,
    merged_versions,
    read,
    verify,
)
from aef.harness.proposer import Citation, Proposal
from aef.harness.review import Disposition, decide, render_diff, render_report
from aef.observability.in_memory import InMemoryTracer

AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
CITE = (Citation(source="s1", split=Split.TRAIN, detail="two timeouts"),)


def _append(root: Path, n: int = 1, **overrides: object) -> None:
    for i in range(n):
        kwargs: dict[str, object] = {
            "kind": EventKind.PROPOSED,
            "at": AT + timedelta(minutes=i),
            "proposal_id": f"p{i}",
            "summary": f"proposal {i}",
        }
        kwargs.update(overrides)
        append(root, **kwargs)  # type: ignore[arg-type]


def _proposal() -> Proposal:
    return Proposal(
        id="p1",
        path="agents/planner.py",
        original="RETRY_LIMIT = 3\n",
        proposed="RETRY_LIMIT = 4\n",
        rationale="two recorded timeouts on s1",
        grounded_in=CITE,
    )


# --------------------------------------------------------------------------
# The ledger — append-only and tamper-evident
# --------------------------------------------------------------------------


def test_an_empty_ledger_reads_as_empty(tmp_path: Path) -> None:
    assert read(tmp_path) == ()


def test_entries_are_sequenced_and_chained(tmp_path: Path) -> None:
    _append(tmp_path, 3)
    entries = read(tmp_path)
    assert [e.sequence for e in entries] == [1, 2, 3]
    assert entries[1].previous_hash == entries[0].entry_hash
    assert entries[2].previous_hash == entries[1].entry_hash


def test_the_first_entry_chains_to_genesis(tmp_path: Path) -> None:
    _append(tmp_path)
    assert read(tmp_path)[0].previous_hash == "0" * 64


def test_altering_an_entry_is_detected(tmp_path: Path) -> None:
    """THE tamper test. A system that can merge its own changes could also,
    in principle, edit the record of having done so."""
    _append(tmp_path, 3)
    path = tmp_path / "ledger.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    lines[1] = lines[1].replace("proposal 1", "something else entirely")
    path.write_text("".join(lines))

    with pytest.raises(LedgerTamperedError, match="hash mismatch"):
        read(tmp_path)


def test_removing_an_entry_is_detected(tmp_path: Path) -> None:
    _append(tmp_path, 3)
    path = tmp_path / "ledger.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    path.write_text(lines[0] + lines[2])  # drop the middle

    with pytest.raises(LedgerTamperedError):
        read(tmp_path)


def test_reordering_entries_is_detected(tmp_path: Path) -> None:
    _append(tmp_path, 3)
    path = tmp_path / "ledger.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    path.write_text(lines[0] + lines[2] + lines[1])

    with pytest.raises(LedgerTamperedError):
        read(tmp_path)


def test_a_truncated_tail_line_fails_the_chain_rather_than_being_absorbed(
    tmp_path: Path,
) -> None:
    _append(tmp_path, 2)
    path = tmp_path / "ledger.jsonl"
    path.write_text(path.read_text()[:-30])
    with pytest.raises(LedgerError):
        read(tmp_path)


def test_appending_onto_a_broken_chain_is_refused(tmp_path: Path) -> None:
    # Extending damage would make the tampering harder to locate.
    _append(tmp_path, 2)
    path = tmp_path / "ledger.jsonl"
    path.write_text(path.read_text().replace("proposal 0", "edited"))

    with pytest.raises(LedgerTamperedError):
        _append(tmp_path)


def test_verify_returns_the_entry_count(tmp_path: Path) -> None:
    _append(tmp_path, 4)
    assert verify(tmp_path) == 4


# --------------------------------------------------------------------------
# Bisection — what M10 acts on
# --------------------------------------------------------------------------


def test_history_for_one_proposal_is_retrievable(tmp_path: Path) -> None:
    append(tmp_path, kind=EventKind.PROPOSED, at=AT, proposal_id="p1", summary="proposed")
    append(tmp_path, kind=EventKind.GATED, at=AT, proposal_id="p2", summary="other")
    append(tmp_path, kind=EventKind.MERGED, at=AT, proposal_id="p1", summary="merged")

    kinds = [e.kind for e in history_for(tmp_path, "p1")]
    assert kinds == [EventKind.PROPOSED, EventKind.MERGED]


def test_merges_index_to_archive_versions_for_bisection(tmp_path: Path) -> None:
    # A regression found in production must be walkable back to the change
    # that introduced it without guesswork.
    append(
        tmp_path,
        kind=EventKind.MERGED,
        at=AT,
        proposal_id="p1",
        summary="merged",
        detail={"archive_version": 7},
    )
    append(tmp_path, kind=EventKind.REJECTED, at=AT, proposal_id="p2", summary="rejected")
    append(
        tmp_path,
        kind=EventKind.MERGED,
        at=AT,
        proposal_id="p3",
        summary="merged",
        detail={"archive_version": 8},
    )
    assert merged_versions(tmp_path) == (("p1", 7), ("p3", 8))


def test_every_event_kind_round_trips(tmp_path: Path) -> None:
    for i, kind in enumerate(EventKind):
        append(tmp_path, kind=kind, at=AT, proposal_id=f"p{i}", summary=str(kind))
    assert [e.kind for e in read(tmp_path)] == list(EventKind)


# --------------------------------------------------------------------------
# The review surface — decision first, diff last
# --------------------------------------------------------------------------


def _result(*results: GateResult) -> PipelineResult:
    return PipelineResult(results=results)


def _passed(gate: str) -> GateResult:
    return GateResult(gate=gate, outcome=GateOutcome.PASS, reason="ok")


def test_a_failing_pipeline_rejects() -> None:
    result = _result(_passed("G0"), GateResult(gate="G1", outcome=GateOutcome.FAIL, reason="boom"))
    decision = decide(result, tier1_enabled=False)
    assert decision.disposition is Disposition.REJECT
    assert "G1" in decision.reason


def test_a_security_event_rejects_rather_than_escalating() -> None:
    result = _result(
        GateResult(gate="G0", outcome=GateOutcome.FAIL, reason="zone b", security_event=True)
    )
    assert decide(result, tier1_enabled=False).disposition is Disposition.REJECT


def test_a_fully_passing_pipeline_escalates_while_tier1_is_off() -> None:
    # ADR 0045: Tier-1 stays off until M10's monitoring exists. With no human
    # in the merge path AND nothing watching afterwards, an auto-merge is
    # unobserved in both directions.
    decision = decide(_result(_passed("G0"), _passed("G1")), tier1_enabled=False)
    assert decision.disposition is Disposition.ESCALATE
    assert "monitoring" in decision.question


def test_the_escalation_question_is_answerable_without_reading_code() -> None:
    decision = decide(_result(_passed("G0")), tier1_enabled=False)
    assert decision.question.endswith("?")
    assert "diff" not in decision.question.lower()


def test_a_fully_passing_pipeline_auto_merges_once_tier1_is_enabled() -> None:
    decision = decide(_result(_passed("G0"), _passed("G1")), tier1_enabled=True)
    assert decision.disposition is Disposition.AUTO_MERGE


def test_an_empty_pipeline_rejects_rather_than_merging() -> None:
    assert decide(_result(), tier1_enabled=True).disposition is Disposition.REJECT


def test_the_report_leads_with_the_decision_not_the_diff() -> None:
    # A report opening with a diff invites the rubber stamp the tiered policy
    # exists to eliminate.
    report = render_report(
        _proposal(), _result(_passed("G0")), decide(_result(_passed("G0")), tier1_enabled=False)
    )
    assert report.index("What is being asked") < report.index("The change itself")


def test_the_report_names_the_evidence_and_the_gate_numbers() -> None:
    result = _result(GateResult(gate="G0", outcome=GateOutcome.PASS, reason="1 file, 2 lines"))
    report = render_report(_proposal(), result, decide(result, tier1_enabled=False))
    assert "s1 (train)" in report
    assert "1 file, 2 lines" in report


def test_the_report_says_plainly_when_no_gates_ran() -> None:
    report = render_report(_proposal(), _result(), decide(_result(), tier1_enabled=False))
    assert "not the same as passing" in report


def test_the_diff_is_rendered_unified() -> None:
    diff = render_diff(_proposal())
    assert "-RETRY_LIMIT = 3" in diff
    assert "+RETRY_LIMIT = 4" in diff


# --------------------------------------------------------------------------
# Gate observability
# --------------------------------------------------------------------------


class _Stub(Gate):
    def __init__(self, gate_id: str, outcome: GateOutcome) -> None:
        self.id = gate_id
        self._outcome = outcome

    def run(self, ctx: GateContext) -> GateResult:
        return GateResult(gate=self.id, outcome=self._outcome, reason="stub")


def test_each_gate_run_emits_a_span(tmp_path: Path) -> None:
    tracer = InMemoryTracer()
    ctx = GateContext(
        repo=None,  # type: ignore[arg-type]
        base_ref="base",
        head_ref="cand",
        verdict=None,  # type: ignore[arg-type]
        workdir=tmp_path,
        tracer=tracer,
    )
    run_pipeline([_Stub("G0", GateOutcome.PASS), _Stub("G1", GateOutcome.PASS)], ctx)

    names = [s.name for s in tracer.spans]
    assert names == ["aef.harness.gate.G0", "aef.harness.gate.G1"]


def test_the_span_records_the_gate_outcome(tmp_path: Path) -> None:
    tracer = InMemoryTracer()
    ctx = GateContext(
        repo=None,  # type: ignore[arg-type]
        base_ref="base",
        head_ref="cand",
        verdict=None,  # type: ignore[arg-type]
        workdir=tmp_path,
        tracer=tracer,
    )
    run_pipeline([_Stub("G0", GateOutcome.FAIL)], ctx)

    assert tracer.spans[0].attributes["aef.gate.outcome"] == "fail"


def test_the_pipeline_runs_without_a_tracer(tmp_path: Path) -> None:
    ctx = GateContext(
        repo=None,  # type: ignore[arg-type]
        base_ref="base",
        head_ref="cand",
        verdict=None,  # type: ignore[arg-type]
        workdir=tmp_path,
    )
    assert run_pipeline([_Stub("G0", GateOutcome.PASS)], ctx).passed
