"""The trust case must stay true, or it is worse than absent.

A document asserting a recommendation and a residual-risk number goes stale
silently: nothing fails when the thing it describes changes. These tests pin
the claims that would MOST mislead an owner if they drifted — above all that
Tier-1 is still off, since the whole document is advice about not enabling it.
"""

from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[2] / "docs" / "trust" / "promotion-trust-case.md"


@pytest.fixture(scope="module")
def text() -> str:
    """Whitespace-normalised. The document is hard-wrapped, so a claim can be
    split across a line break and a naive substring check would report it
    missing — a test that fails on the prose's formatting rather than on its
    content teaches everyone to stop reading it."""
    return " ".join(CASE.read_text().split())


def test_the_trust_case_exists_and_recommends(text: str) -> None:
    assert "Recommendation: no" in text
    assert "Do not enable Tier-1 auto-merge." in text


def test_the_document_still_describes_a_disabled_switch() -> None:
    """The claim the whole document rests on. If Tier-1 were ever enabled, the
    recommendation would be describing a decision already taken."""
    from aef.harness.review import Disposition

    assert hasattr(Disposition, "ESCALATE")
    from aef.harness import loop

    source = Path(loop.__file__).read_text()
    assert "auto_merge" not in source or "tier1_auto_merge = True" not in source


def test_a_fully_passing_candidate_still_escalates() -> None:
    """Behaviour, not prose. The transcript in §1 ends `DISPOSITION: ESCALATE
    — every gate passed, but Tier-1 auto-merge is not enabled`, and that is
    the sentence an owner reads the rest of the document against."""
    from aef.harness.gates.base import GateOutcome, GateResult, PipelineResult
    from aef.harness.review import Disposition, decide

    passing = PipelineResult(
        results=tuple(
            GateResult(gate=g, outcome=GateOutcome.PASS, reason="ok")
            for g in ("G0", "G1", "G4", "G5", "G2", "G3")
        )
    )
    decision = decide(passing, tier1_enabled=False)
    assert decision.disposition is Disposition.ESCALATE, (
        "a fully passing candidate no longer escalates — the trust case's central "
        "transcript is stale and its recommendation is about a switch already thrown"
    )

    # And every production caller must still pass False. The parameter existing
    # is not the control; nobody setting it is.
    import subprocess

    hits = subprocess.run(
        ["grep", "-rn", "tier1_enabled", "aef/"],
        capture_output=True,
        text=True,
        cwd=str(CASE.resolve().parents[2]),
    ).stdout.splitlines()
    enabled_true = [h for h in hits if "tier1_enabled=True" in h.replace(" ", "")]
    assert not enabled_true, f"Tier-1 is enabled somewhere in aef/: {enabled_true}"


def test_the_contained_shadow_path_the_document_claims_exists(text: str) -> None:
    """§2.1 now claims the bypass is closed by running the candidate inside a
    container. A document claiming a fix that is not importable is worse than
    one that never claimed it."""
    from aef.harness.shadow import contained_candidate_graph

    assert callable(contained_candidate_graph)
    assert "now fixed, and the fix is verified in both directions" in text
    assert "Containment is now the DEFAULT" in text

    # And the document must not still be describing it as opt-in.
    from aef.harness.shadow import ShadowRunner, UncontainedShadowError
    from aef.kernel import END, Graph, Node
    from aef.state import StateDelta

    def w(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(), END

    graph = Graph(
        id="g",
        version="1",
        nodes={"w": Node(id="w", version="1", fn=w, deterministic=True)},
        edges=[],
        entry_node="w",
    )
    with pytest.raises(UncontainedShadowError):
        ShadowRunner(incumbent=graph, candidate=graph)


def test_the_residual_risk_is_a_number_with_a_basis(text: str) -> None:
    """6c: "None" is not an answer, it is an absence of one."""
    assert "5 to 10 false accepts" in text
    assert "derived, not measured" in text
    assert "p95" in text


def test_the_adversarial_section_reports_failures_not_only_successes(text: str) -> None:
    """A list of attacks that all held is a claim of completeness, which this
    program has three ADRs recording as a mistake."""
    assert text.count("BROKE IT") >= 2
    assert "demonstrated bypass" in text


def test_the_known_canary_limit_is_still_a_limit() -> None:
    """§2.2 tells an owner a narrow regression is invisible. If coverage
    improved and this went unstated, the document would be understating the
    harness — which is the safer direction, and still wrong."""
    from aef.harness.canary import CanaryState

    state = CanaryState(graph_id="g", candidate_version=2, warm_version=1)
    verdict = state.evaluate(
        candidate_samples=[10.0] * 995 + [10_000.0] * 5,
        incumbent_samples=[10.0] * 1000,
    )
    assert verdict.passed, (
        "coverage improved: update docs/trust/promotion-trust-case.md §2.2 and "
        "DEFAULT_PERCENTILES together"
    )


def test_the_in_process_shadow_bypass_is_still_real_when_opted_into() -> None:
    """§2.1 says the bypass is closed by containment, which is now the DEFAULT.
    The uncontained mode still exists and still has the bypass — that is why
    opting into it is explicit and recorded on every observation.

    If the uncontained path ever contains its candidates too, §2.1 is
    understating the harness and should be updated.
    """
    import tempfile

    from aef.harness.shadow import ShadowRunner
    from aef.kernel import END, Graph, Node
    from aef.services.runtime import agent_services
    from aef.state import AEFState, StateDelta

    marker = Path(tempfile.mkdtemp()) / "shadow_did_io"

    def writes(state, ctx, services):  # type: ignore[no-untyped-def]
        marker.write_text("the shadow wrote this")
        return StateDelta(), END

    def clean(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(), END

    def graph(fn, name):  # type: ignore[no-untyped-def]
        return Graph(
            id=name,
            version="1",
            nodes={"w": Node(id="w", version="1", fn=fn, deterministic=True)},
            edges=[],
            entry_node="w",
        )

    ShadowRunner(
        incumbent=graph(clean, "i"), candidate=graph(writes, "c"), uncontained=True
    ).observe(AEFState(run_id="r", agent_id="a", objective="o"), agent_services())
    assert marker.exists(), (
        "the in-process shadow no longer performs direct I/O: §2.1 of the trust case is "
        "stale, and reason #2 of the recommendation rests partly on it"
    )
