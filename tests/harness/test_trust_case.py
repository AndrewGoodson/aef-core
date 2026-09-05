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


def test_every_attack_the_document_names_has_a_module_that_runs_it() -> None:
    """The replacement for a grep, and the reason it is a replacement.

    This test used to be a comment. It listed each attack beside whichever
    existing test happened to exercise the same control, and asserted the
    document still said `BROKE IT` twice — a mapping maintained by hand, in
    prose, inside a test that could not detect it going stale. An independent
    reviewer read the result exactly as it deserved (ADR 0188, dim 4):
    *"adversarial rounds exist as a document I was not allowed to read, not as
    an executable red-team suite."*

    `tests/adversarial/` is that suite (ADR 0194). What this test does now is
    the one job the grep was attempting: keep the DOCUMENT and the SUITE from
    drifting apart. It is deliberately bidirectional —

      * an attack named here with no module is a claim with nothing behind it;
      * a module with no attack named here is a control being exercised that
        the owner reading this document is never told about.

    Neither direction can be satisfied by editing prose.
    """
    import re

    root = CASE.resolve().parents[2]
    suite = root / "tests" / "adversarial"
    assert suite.is_dir(), "the adversarial suite is gone; this document's §2 is prose again"

    # `A1 ... A17` as the document writes them: at a line start or after a
    # space, followed by a space. Not a bare `\bA\d+\b`, which would also match
    # "ADR" numbers and section references.
    named = {
        int(m.group(1))
        for m in re.finditer(r"(?:^| )A(\d{1,2}) ", " ".join(CASE.read_text().split()))
    }
    modules = {
        int(m.group(1))
        for path in suite.glob("test_a*.py")
        if (m := re.match(r"test_a(\d{1,2})_", path.name))
    }

    assert named, "no attack ids found in the trust case; the parser or the document moved"
    missing = sorted(named - modules)
    assert not missing, (
        f"the trust case names attacks {missing} with no module in tests/adversarial/ — "
        f"a claim with nothing behind it"
    )
    unlisted = sorted(modules - named)
    assert not unlisted, (
        f"tests/adversarial/ runs attacks {unlisted} the trust case never mentions — "
        f"an owner reading §2 is not being told what was tried"
    )


def test_every_adversarial_module_carries_a_mutation() -> None:
    """The property that makes the suite a red team rather than a green bar.

    A module that only asserts refusals passes identically whether the defence
    works or the exploit was never viable. Every module must therefore also
    remove its own control and assert the attack lands — named by convention,
    `test_a<n>_the_control_is_load_bearing`, so this check is a fact about the
    files rather than a hope about their contents.
    """
    import re

    suite = CASE.resolve().parents[2] / "tests" / "adversarial"
    without = [
        path.name
        for path in sorted(suite.glob("test_a*.py"))
        if not re.search(r"def test_a\d{1,2}_the_control_is_load_bearing", path.read_text())
    ]
    assert not without, (
        f"{without} assert refusals with no mutation proving the control is what refused"
    )


def test_the_known_canary_limit_is_still_a_limit() -> None:
    """§2.2 tells an owner a narrow regression is invisible. If coverage
    improved and this went unstated, the document would be understating the
    harness — which is the safer direction, and still wrong."""
    from aef.harness.canary import CanarySalt, CanaryState

    state = CanaryState(
        graph_id="g",
        candidate_version=2,
        warm_version=1,
        # Keyed, because that is now the default (ADR 0106). The percentile
        # limit this test pins has nothing to do with assignment.
        salt=CanarySalt(material=b"trust-case-salt-exactly-32-byte!"),
    )
    verdict = state.evaluate(
        candidate_samples=[10.0] * 995 + [10_000.0] * 5,
        incumbent_samples=[10.0] * 1000,
    )
    assert verdict.passed, (
        "coverage improved: update docs/trust/promotion-trust-case.md §2.2 and "
        "DEFAULT_PERCENTILES together"
    )


def test_the_in_process_bypass_exists_only_when_an_owner_opts_out_and_is_logged(
    tmp_path: Path,
) -> None:
    """What §2.1 now claims, in both halves (ADR 0161).

    The earlier name — `..._is_still_real_when_opted_into` — read as a
    concession that an uncontained path remains, and an independent reviewer
    read it exactly that way (ADR 0151, dim 4). Both halves are the point:

    1. The bypass IS still real under the opt-out. A control you cannot
       demonstrate is decoration, and if this half ever stopped failing, §2.1
       would be understating the harness rather than overstating it.
    2. It is reached ONLY by an owner writing `shadow.containment: fallback`
       or `off`. `auto` — the default — refuses instead of running, and the
       opt-out is announced and written to the ledger as a security event, so
       nobody reads the resulting evidence without knowing what it cost.
    """
    import tempfile

    from aef.harness.ledger import EventKind, read
    from aef.harness.shadow import ContainmentMode, UncontainedShadowError, shadow_for
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

    announced: list[str] = []
    shadow = shadow_for(
        graph(clean, "i"),
        entrypoint="unused:build_graph",
        workdir=tmp_path,
        image="aef-worker:test",
        mode=ContainmentMode.OFF,
        in_process_candidate=graph(writes, "c"),
        ledger_root=tmp_path,
        proposal_id="trust-case",
        warn=announced.append,
    )
    observation = shadow.runner.observe(
        AEFState(run_id="r", agent_id="a", objective="o"), agent_services()
    )

    assert marker.exists(), (
        "the in-process shadow no longer performs direct I/O: §2.1 of the trust case is "
        "stale, and reason #2 of the recommendation rests partly on it"
    )
    assert observation.contained is False
    assert announced and "OFF by owner choice" in announced[0], "the opt-out was silent"
    (entry,) = read(tmp_path)
    assert entry.kind is EventKind.CONTAINMENT
    assert entry.detail["security_event"] is True
    assert entry.detail["containment"]["owner_opted_out"] is True

    # And the default cannot get there: no owner statement, no bypass. The
    # mode is read from the config path (ADR 0173) because that is now where
    # "the default" lives — `shadow_for` has no default of its own.
    from aef.cli.run import build_run_config

    with pytest.raises(UncontainedShadowError):
        shadow_for(
            graph(clean, "i"),
            entrypoint="unused:build_graph",
            workdir=tmp_path,
            image=None,
            mode=build_run_config(None).containment_mode,
            in_process_candidate=graph(writes, "c"),
        )
