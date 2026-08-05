"""Milestone 5: the three Phase-4 criteria that were missing.

Quoted verbatim from `docs/roadmap.md`, because the milestone was explicit
that paraphrasing them into something easier is the failure mode:

  1. Shadow execution against live traffic before promotion eligibility
  6. Canary rollout stratified by tenant tag, gated on percentiles, previous
     version kept warm for rollback
  7. Human-in-the-loop approval above a configurable risk threshold, signed
     release manifests

Each requirement in those sentences gets its own test, and each test is
written so it can fail: a control alongside every claim, because "the
candidate agreed with the incumbent" and "the comparison never ran" produce
the same green.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.canary import (
    CanaryError,
    CanaryPolicy,
    CanaryState,
    CanaryVerdict,
    assigned_to_candidate,
    percentile,
)
from aef.harness.release import (
    MANIFEST_VERSION,
    ReleaseError,
    ReleaseManifest,
    SignatureError,
    SignedRelease,
    SigningKey,
    sign,
    verify,
)
from aef.harness.shadow import (
    ShadowError,
    ShadowReport,
    ShadowRunner,
    UnsuppressableSideEffectError,
    assert_shadowable,
)
from aef.kernel import END, Graph, Node
from aef.kernel.contracts import SideEffect
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
KEY = SigningKey(material=b"k" * 32)


# ==========================================================================
# Criterion 1 — shadow execution
# ==========================================================================


def _graph(graph_id: str, *, value: str, side_effects: SideEffect = SideEffect.PURE) -> Graph:
    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(working_memory={"answer": value}), END

    kwargs: dict[str, object] = {"side_effects": side_effects}
    if side_effects is not SideEffect.PURE:
        kwargs["idempotency_key_fn"] = lambda s: s.run_id
    return Graph(
        id=graph_id,
        version="1",
        nodes={"work": Node(id="work", version="1", fn=work, deterministic=True, **kwargs)},  # type: ignore[arg-type]
        edges=[],
        entry_node="work",
    )


def _state() -> AEFState:
    return AEFState(run_id="live-1", agent_id="a", objective="serve a real request")


def test_the_user_gets_the_incumbents_answer_when_the_candidate_disagrees() -> None:
    """ "nothing it returns reaches a user". Asserted on the value actually
    handed back, not on a flag saying it was suppressed."""
    runner = ShadowRunner(
        incumbent=_graph("g", value="incumbent"), candidate=_graph("g", value="candidate")
    )
    observation = runner.observe(_state(), agent_services())
    assert observation.state.working_memory["answer"] == "incumbent"
    assert observation.divergence.diverged


def test_there_is_no_way_to_reach_the_candidates_result() -> None:
    """Structural, not a convention. A shadow result a caller can reach for is
    one that eventually reaches a user."""
    runner = ShadowRunner(incumbent=_graph("g", value="a"), candidate=_graph("g", value="b"))
    observation = runner.observe(_state(), agent_services())
    for attribute in vars(observation):
        assert "candidate" not in attribute, (
            f"ShadowObservation exposes {attribute!r}, a route to the shadow's output"
        )


def test_agreement_is_reported_as_agreement() -> None:
    """The control for the divergence test. If everything read as divergent
    the assertion above would pass while measuring nothing."""
    runner = ShadowRunner(incumbent=_graph("g", value="same"), candidate=_graph("g", value="same"))
    observation = runner.observe(_state(), agent_services())
    assert observation.agreed
    assert observation.divergence.fields == ()


def test_only_the_divergence_is_recorded_not_both_outputs() -> None:
    """A shadow log holding every candidate output is a second copy of
    production data with none of its access controls."""
    secret = "SHADOW-ONLY-VALUE-Q7X"
    runner = ShadowRunner(
        incumbent=_graph("g", value="served"), candidate=_graph("g", value=secret)
    )
    divergence = runner.observe(_state(), agent_services()).divergence
    assert divergence.fields == ("working_memory",)
    assert secret not in repr(divergence), "the shadow's output leaked into the divergence record"


def test_a_mutating_candidate_is_refused_before_any_live_request() -> None:
    """The part that cannot be paraphrased away: shadowing runs the candidate
    on LIVE input, so a mutating node mutates — for real, a second time. The
    policy engine denies tool calls; it cannot un-write a write."""
    mutating = _graph("g", value="x", side_effects=SideEffect.MUTATING)
    with pytest.raises(UnsuppressableSideEffectError, match="mutating"):
        assert_shadowable(mutating)
    with pytest.raises(UnsuppressableSideEffectError):
        ShadowRunner(incumbent=_graph("g", value="x"), candidate=mutating)


def test_a_pure_candidate_is_shadowable() -> None:
    """The control: if everything were refused, the test above would pass for
    the wrong reason."""
    assert_shadowable(_graph("g", value="x"))


def test_a_crashing_candidate_does_not_break_the_live_request() -> None:
    """Observing a candidate must never be more dangerous than not observing
    it. The incumbent has already answered; the shadow's failure is evidence,
    not an outage."""

    def boom(state, ctx, services):  # type: ignore[no-untyped-def]
        raise RuntimeError("candidate exploded")

    broken = Graph(
        id="g",
        version="1",
        nodes={"work": Node(id="work", version="1", fn=boom, deterministic=True)},
        edges=[],
        entry_node="work",
    )
    observation = ShadowRunner(incumbent=_graph("g", value="ok"), candidate=broken).observe(
        _state(), agent_services()
    )

    assert observation.state.working_memory["answer"] == "ok"
    assert "candidate exploded" in observation.divergence.candidate_failed
    assert observation.divergence.diverged


def test_the_shadow_does_not_inherit_the_incumbents_hitl_approvals() -> None:
    """An approval the owner granted for the incumbent's call is not an
    approval for the candidate's."""
    from aef.harness.shadow import _suppressed_services

    base = agent_services()
    granted = type(base)(**{**vars(base), "hitl_approvals": frozenset({"a->b"})})
    assert _suppressed_services(granted).hitl_approvals == frozenset()


def test_the_shadow_runs_under_deny_by_default() -> None:
    """Reusing the engine's own default rather than a bespoke shadow mode:
    two security decisions to keep in agreement is how the service lists
    drifted (ADR 0091)."""
    from aef.harness.shadow import _suppressed_services

    engine = _suppressed_services(agent_services()).policy_engine
    assert engine is not None
    assert engine._config.allowed_scopes == frozenset()
    assert engine._config.forbidden_tool_names == frozenset()


def test_a_divergence_rate_over_zero_observations_is_undefined() -> None:
    """0.0 would make "never ran" indistinguishable from "always agreed", and
    the second is the one that earns promotion."""
    with pytest.raises(ShadowError, match="undefined"):
        _ = ShadowReport().divergence_rate


def test_the_report_accumulates_which_fields_diverge() -> None:
    runner = ShadowRunner(incumbent=_graph("g", value="a"), candidate=_graph("g", value="b"))
    report = ShadowReport()
    for _ in range(3):
        report = report.with_observation(runner.observe(_state(), agent_services()))
    assert report.observations == 3
    assert report.divergences == 3
    assert report.divergence_rate == 1.0
    assert report.diverging_fields == {"working_memory": 3}


# ==========================================================================
# Criterion 6 — canary rollout
# ==========================================================================


def test_assignment_is_stable_for_a_tenant() -> None:
    """ "stratified by tenant tag". A tenant flipping arms between requests
    sees inconsistent behaviour AND contributes to both arms, which averages
    the difference into invisibility."""
    first = assigned_to_candidate("tenant-7", graph_id="g", version=2, percent=25)
    for _ in range(50):
        assert assigned_to_candidate("tenant-7", graph_id="g", version=2, percent=25) is first


def test_assignment_is_monotone_in_exposure() -> None:
    """A tenant admitted at 5% must still be admitted at 25%. Otherwise
    advancing a stage reshuffles the population and discards every sample
    gathered so far, while appearing to accumulate evidence."""
    tags = [f"tenant-{i}" for i in range(400)]
    previous: set[str] = set()
    for percent in (1, 5, 25, 50, 100):
        admitted = {
            t for t in tags if assigned_to_candidate(t, graph_id="g", version=1, percent=percent)
        }
        assert previous <= admitted, f"tenants dropped out of the candidate arm at {percent}%"
        previous = admitted
    assert previous == set(tags), "100% did not admit everyone"


def test_exposure_is_approximately_the_stage_percentage() -> None:
    tags = [f"tenant-{i}" for i in range(2000)]
    admitted = sum(assigned_to_candidate(t, graph_id="g", version=1, percent=25) for t in tags)
    assert 0.20 < admitted / len(tags) < 0.30


def test_a_new_version_reshuffles_who_is_exposed() -> None:
    """The same tenants should not always be the guinea pigs."""
    tags = [f"tenant-{i}" for i in range(500)]
    v1 = {t for t in tags if assigned_to_candidate(t, graph_id="g", version=1, percent=10)}
    v2 = {t for t in tags if assigned_to_candidate(t, graph_id="g", version=2, percent=10)}
    assert v1 != v2


def test_an_untagged_request_is_refused_rather_than_defaulted() -> None:
    """Defaulting to the incumbent would silently exempt whoever forgot the
    tag, and the exemption would look like a passing canary."""
    with pytest.raises(CanaryError, match="empty tag"):
        assigned_to_candidate("", graph_id="g", version=1, percent=50)


def _samples(value: float, n: int = 200) -> list[float]:
    return [value] * n


def _state_at(index: int = 0) -> CanaryState:
    return CanaryState(graph_id="g", candidate_version=2, warm_version=1, stage_index=index)


def test_a_tail_regression_is_caught_when_the_median_improves() -> None:
    """ "gated on percentiles" — the whole reason it is not gated on means. A
    candidate that is better for almost everyone and far worse for the last
    1% is what a mean hides and what users notice."""
    incumbent = [10.0] * 950 + [11.0] * 50
    candidate = [9.0] * 950 + [100.0] * 50  # better median, catastrophic tail

    assert sum(candidate) / len(candidate) < sum(incumbent) / len(incumbent) * 2, (
        "the fixture's mean must not itself be alarming, or this proves nothing"
    )
    assert percentile(candidate, 50) < percentile(incumbent, 50), (
        "the fixture must IMPROVE the median, or this is an ordinary regression test"
    )
    verdict = _state_at().evaluate(candidate_samples=candidate, incumbent_samples=incumbent)
    assert not verdict.passed
    assert "p95" in verdict.reason or "p99" in verdict.reason


def test_a_regression_narrower_than_the_smallest_percentile_is_INVISIBLE() -> None:
    """Found by running, while writing the test above. Recorded rather than
    tuned away.

    p99 answers "99% are at or below this", so a regression confined to the
    worst 1% sits ENTIRELY ABOVE it and no configured percentile sees it. The
    first draft of the fixture above used exactly 1% and passed the gate; that
    was not a fixture bug, it was the gate's coverage limit showing.

    This is a real ceiling on what a canary can catch, and the honest response
    is to state it and let an owner add p99.9 knowing why — not to widen the
    fixture until the assertion goes green.
    """
    incumbent = [10.0] * 1000
    candidate = [10.0] * 995 + [10_000.0] * 5  # 0.5%: catastrophic, and unseen

    verdict = _state_at().evaluate(candidate_samples=candidate, incumbent_samples=incumbent)
    assert verdict.passed, "coverage improved — update this test and DEFAULT_PERCENTILES together"

    widened = CanaryState(
        graph_id="g",
        candidate_version=2,
        warm_version=1,
        policy=CanaryPolicy(percentiles=(50, 95, 99, 100)),
    )
    caught = widened.evaluate(candidate_samples=candidate, incumbent_samples=incumbent)
    assert not caught.passed, "the limitation is not a percentile-coverage one after all"
    assert "p100" in caught.reason


def test_an_equivalent_candidate_passes() -> None:
    """The control. If every comparison failed, the test above would prove
    nothing about percentiles."""
    verdict = _state_at().evaluate(
        candidate_samples=_samples(10.0), incumbent_samples=_samples(10.0)
    )
    assert verdict.passed, verdict.reason
    assert len(verdict.measurements) == 3


def test_too_few_samples_is_keep_watching_not_regressed() -> None:
    """A percentile over 20 observations is a number without a claim."""
    verdict = _state_at().evaluate(
        candidate_samples=_samples(10.0, 20), incumbent_samples=_samples(10.0, 20)
    )
    assert not verdict.passed
    assert "below the floor" in verdict.reason


def test_the_previous_version_is_kept_warm() -> None:
    """ "previous version kept warm for rollback". A rollback target that has
    to be rebuilt is an outage with a plan."""
    state = _state_at()
    assert state.warm_version == 1
    rolled = state.rollback(
        CanaryVerdict(stage_percent=1, passed=False, reason="p99 regressed"), at=NOW
    )
    assert rolled.warm_version == 1
    assert any("rollback" in entry and "v1" in entry for entry in rolled.history)


def test_a_rollout_with_nothing_to_roll_back_to_is_refused() -> None:
    with pytest.raises(CanaryError, match="nothing to roll back"):
        CanaryState(graph_id="g", candidate_version=2, warm_version=2)


def test_the_ladder_advances_one_rung_at_a_time() -> None:
    state = _state_at()
    percents = [state.percent]
    while not state.complete:
        verdict = state.evaluate(candidate_samples=_samples(10.0), incumbent_samples=_samples(10.0))
        state = state.advance(verdict, at=NOW)
        percents.append(state.percent)
    assert percents == [1, 5, 25, 50, 100]


def test_advancing_past_a_failure_is_refused() -> None:
    state = _state_at()
    verdict = state.evaluate(candidate_samples=_samples(100.0), incumbent_samples=_samples(10.0))
    assert not verdict.passed
    with pytest.raises(CanaryError, match="cannot advance"):
        state.advance(verdict, at=NOW)


def test_a_verdict_from_another_stage_cannot_promote_this_one() -> None:
    """A 1% stage's evidence describes a different population than a 50%
    stage's."""
    state = _state_at(index=3)  # 50%
    stale = CanaryVerdict(stage_percent=1, passed=True, reason="fine at 1%")
    with pytest.raises(CanaryError, match="different population"):
        state.advance(stale, at=NOW)


def test_a_ladder_that_never_reaches_100_is_refused() -> None:
    with pytest.raises(CanaryError, match="last stage must be 100"):
        CanaryPolicy(ladder=(1, 5, 50))


def test_a_ladder_that_narrows_is_refused() -> None:
    with pytest.raises(CanaryError, match="strictly increasing"):
        CanaryPolicy(ladder=(1, 50, 25, 100))


def test_percentiles_are_nearest_rank_not_interpolated() -> None:
    """Nearest-rank returns a number that actually happened, which is what an
    operator asked to explain a rollback can point at."""
    samples = [1.0, 2.0, 3.0, 4.0]
    assert percentile(samples, 50) == 2.0
    assert percentile(samples, 100) == 4.0
    for p in (25, 50, 75, 99, 100):
        assert percentile(samples, p) in samples


# ==========================================================================
# Criterion 7 — signed release manifests
# ==========================================================================


def _manifest(**kw: object) -> ReleaseManifest:
    base: dict[str, object] = {
        "graph_id": "demo_agent",
        "version": 3,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "evidence": {"G0": "pass", "G3": "pass"},
        "approved_by": "owner@example.com",
        "approved_at": NOW,
    }
    base.update(kw)
    return ReleaseManifest(**base)  # type: ignore[arg-type]


def test_a_valid_signature_verifies() -> None:
    manifest = _manifest()
    verify(manifest, sign(manifest, KEY), KEY)


def test_altering_the_evidence_invalidates_the_signature() -> None:
    """ADR 0087's hole: a forger who rebuilds a consistent chain replays
    clean. The evidence is IN the signed payload, so keeping the signature
    and swapping the reason does not work."""
    signature = sign(_manifest(), KEY)
    with pytest.raises(SignatureError, match="does not match"):
        verify(_manifest(evidence={"G0": "pass", "G3": "pass", "G5": "pass"}), signature, KEY)

    # And the same for a FAILING gate smuggled in behind a stated override:
    # the override makes the manifest constructible, not the signature valid.
    with pytest.raises(SignatureError, match="does not match"):
        verify(
            _manifest(evidence={"G0": "pass", "G3": "fail"}, override_reason="waived"),
            signature,
            KEY,
        )


def test_altering_the_approver_invalidates_the_signature() -> None:
    signature = sign(_manifest(), KEY)
    with pytest.raises(SignatureError):
        verify(_manifest(approved_by="someone-else@example.com"), signature, KEY)


def test_altering_the_promoted_commit_invalidates_the_signature() -> None:
    signature = sign(_manifest(), KEY)
    with pytest.raises(SignatureError):
        verify(_manifest(head_sha="c" * 40), signature, KEY)


def test_a_different_key_does_not_verify() -> None:
    with pytest.raises(SignatureError):
        verify(_manifest(), sign(_manifest(), KEY), SigningKey(material=b"z" * 32))


def test_a_missing_signature_is_not_quieter_than_a_wrong_one() -> None:
    with pytest.raises(SignatureError, match="not an approval"):
        verify(_manifest(), "", KEY)


def test_an_unevidenced_manifest_cannot_be_built() -> None:
    """An unevidenced approval is exactly the signature a forger wants: valid,
    and about nothing."""
    with pytest.raises(ReleaseError, match="evidence"):
        _manifest(evidence={})


def test_an_unapproved_manifest_cannot_be_built() -> None:
    with pytest.raises(ReleaseError, match="approver"):
        _manifest(approved_by="   ")


def test_a_no_op_manifest_cannot_be_built() -> None:
    """A signature over a promotion that changes nothing is a signature
    waiting to be reused."""
    with pytest.raises(ReleaseError, match="no change to promote"):
        _manifest(head_sha="a" * 40)


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(ReleaseError, match="timezone-aware"):
        _manifest(approved_at=datetime(2026, 3, 1, 12, 0))


def test_the_payload_is_byte_stable_across_reserialisation() -> None:
    """A signature over a re-serialisation must reproduce byte for byte, or a
    manifest verifies only on the machine that signed it — which reads as
    tampering everywhere else."""
    manifest = _manifest(evidence={"G3": "pass", "G0": "pass"})
    reordered = _manifest(evidence={"G0": "pass", "G3": "pass"})
    assert manifest.payload() == reordered.payload()

    round_tripped = SignedRelease.from_payload(
        SignedRelease(manifest=manifest, signature=sign(manifest, KEY)).to_payload()
    )
    verify(round_tripped.manifest, round_tripped.signature, KEY)


def test_a_manifest_from_another_shape_is_refused_not_migrated() -> None:
    """A verifier accepting an older shape checks a different set of claims
    than it believes it is checking."""
    payload = SignedRelease(manifest=_manifest(), signature=sign(_manifest(), KEY)).to_payload()
    payload["manifest"]["manifest_version"] = MANIFEST_VERSION + 1
    with pytest.raises(ReleaseError, match="different set of claims"):
        SignedRelease.from_payload(payload)


def test_a_short_key_is_refused() -> None:
    with pytest.raises(ReleaseError, match="at least"):
        SigningKey(material=b"short")


def test_a_world_readable_key_file_is_refused(tmp_path: Path) -> None:
    """A key any local process can read is not a key the harness is excluded
    from, and the harness runs code it did not write."""
    path = tmp_path / "key"
    path.write_bytes(b"k" * 32)
    path.chmod(0o644)
    with pytest.raises(ReleaseError, match="accessible"):
        SigningKey.from_file(path)

    path.chmod(0o600)
    assert SigningKey.from_file(path).material == b"k" * 32


def test_the_key_never_appears_in_a_repr() -> None:
    """A key in a traceback is a key in a CI log."""
    assert b"k" * 32 not in repr(KEY).encode()
    assert "material" not in repr(KEY)


# ==========================================================================
# The adversarial round for this milestone. Both REPRODUCED first.
# ==========================================================================


def test_a_rolled_back_candidate_does_not_climb_the_ladder_again() -> None:
    """REPRODUCED: `rollback` reset the stage index and nothing recorded that
    the rollout had FAILED, so the next passing verdict sent the same
    candidate straight back up. A candidate with a real regression cycled
    advance -> regress -> rollback -> advance forever, re-exposing users on
    every lap.

    A rollback is a verdict on this candidate, not a reset. What comes next is
    a new version whose evidence is about the fix.
    """
    state = _state_at()
    rolled = state.rollback(
        CanaryVerdict(stage_percent=1, passed=False, reason="p99 regressed"), at=NOW
    )
    assert rolled.rolled_back
    assert rolled.warm_version == 1

    passing = CanaryVerdict(stage_percent=rolled.percent, passed=True, reason="looks fine now")
    with pytest.raises(CanaryError, match="does not climb the ladder again"):
        rolled.advance(passing, at=NOW)


def test_a_fresh_rollout_still_advances() -> None:
    """The control. If `advance` refused everything, the test above would pass
    for the wrong reason."""
    state = _state_at()
    verdict = state.evaluate(candidate_samples=_samples(10.0), incumbent_samples=_samples(10.0))
    assert state.advance(verdict, at=NOW).percent == 5


def test_promoting_over_a_failing_gate_must_be_stated() -> None:
    """REPRODUCED: a manifest whose evidence recorded G3 and G5 as `fail`
    signed and verified cleanly. The artefact that proves "promoted on this
    evidence" was equally happy to prove a rejection had been approved.

    An override is a legitimate owner act. An override nobody had to type is
    an accident waiting to be cited later as intent.
    """
    with pytest.raises(ReleaseError, match="not passing"):
        _manifest(evidence={"G0": "pass", "G3": "fail"})

    stated = _manifest(
        evidence={"G0": "pass", "G3": "fail"},
        override_reason="G3's cohort was undersized; re-run scheduled",
    )
    verify(stated, sign(stated, KEY), KEY)


def test_the_override_reason_is_itself_signed() -> None:
    """An unsigned override is a field a forger can add after the fact to
    explain a signature that was never about it."""
    stated = _manifest(evidence={"G0": "pass", "G3": "fail"}, override_reason="undersized cohort")
    signature = sign(stated, KEY)
    with pytest.raises(SignatureError):
        verify(
            _manifest(evidence={"G0": "pass", "G3": "fail"}, override_reason="looked fine to me"),
            signature,
            KEY,
        )


def test_a_clean_manifest_needs_no_override() -> None:
    """The control: the guard must fire on failures, not on everything."""
    clean = _manifest(evidence={"G0": "pass", "G3": "pass"})
    assert clean.override_reason == ""
    verify(clean, sign(clean, KEY), KEY)


def test_suppression_nulls_no_service_the_incumbent_had() -> None:
    """A shadow missing a service the incumbent had would diverge for a
    harness reason and report it as a candidate defect."""
    from aef.harness.shadow import _suppressed_services

    base = agent_services()
    suppressed = _suppressed_services(base)
    dropped = [
        name
        for name, value in vars(base).items()
        if value is not None and getattr(suppressed, name, None) is None
    ]
    assert dropped == [], f"suppression silently dropped: {dropped}"
