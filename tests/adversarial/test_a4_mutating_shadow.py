"""A4 — shadow a node that declares a MUTATING side effect.

Trust case §2, reported **BROKE IT**, and the reason it broke is the one worth
keeping executable: shadowing runs the candidate on LIVE input, so a mutating
node mutates — for real, a second time, against production. The suppression
the design leaned on is `PolicyEngine` with an empty scope set, and that
denies *tool calls*. A node that writes does not make a tool call.

The fix is a refusal before any live request reaches the runner. This module
constructs the mutating candidate, asserts the refusal, and then removes the
refusal and watches the shadow write to the host — the same demonstration the
document reports as prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aef.harness.shadow import (
    ShadowRunner,
    UnsuppressableSideEffectError,
    assert_shadowable,
)
from aef.kernel import END, Graph, Node
from aef.kernel.contracts import SideEffect
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta


def _state() -> AEFState:
    return AEFState(run_id="live-1", agent_id="a", objective="serve a real request")


def _mutating_graph(marker: Path) -> Graph:
    """The hostile candidate: it declares MUTATING, and it means it."""

    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        marker.write_text("the shadow mutated production", encoding="utf-8")
        return StateDelta(working_memory={"answer": "candidate"}), END

    return Graph(
        id="g",
        version="1",
        nodes={
            "work": Node(
                id="work",
                version="1",
                fn=work,
                deterministic=True,
                side_effects=SideEffect.MUTATING,
                idempotency_key_fn=lambda s: s.run_id,
            )
        },
        edges=[],
        entry_node="work",
    )


def _clean_graph() -> Graph:
    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(working_memory={"answer": "incumbent"}), END

    return Graph(
        id="g",
        version="1",
        nodes={"work": Node(id="work", version="1", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a4_a_mutating_candidate_is_refused_before_any_live_request(tmp_path: Path) -> None:
    marker = tmp_path / "mutated"
    with pytest.raises(UnsuppressableSideEffectError, match="mutating"):
        ShadowRunner(incumbent=_clean_graph(), candidate=_mutating_graph(marker), uncontained=True)
    assert not marker.exists(), "the refusal came after the candidate had already run"


def test_a4_an_external_call_candidate_is_NOT_refused_here_and_that_is_stated() -> None:
    """The boundary of this control, pinned so nobody reads it as wider.

    The trust case's A4 line names EXTERNAL_CALL, and §2.1 then says *"A4 is
    the same finding wearing a declaration"* — meaning the fix for it is A5's
    container, not this refusal. `assert_shadowable` refuses MUTATING only,
    because that is the effect nothing downstream can suppress: a tool call
    can be denied, a write cannot be un-written.

    Written as an attack that gets through on purpose. If this ever starts
    raising, the trust case's mapping of A4 onto containment is stale and
    should be re-read rather than quietly enjoyed.
    """

    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(), END

    external = Graph(
        id="g",
        version="1",
        nodes={
            "work": Node(
                id="work",
                version="1",
                fn=work,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: s.run_id,
            )
        },
        edges=[],
        entry_node="work",
    )
    assert_shadowable(external)  # not this control's job — see test_a5_*

    # And the effect that IS this control's job, on the same graph shape, so
    # the two are compared rather than asserted separately.
    with pytest.raises(UnsuppressableSideEffectError):
        assert_shadowable(_mutating_graph(Path("/nonexistent/never-written")))


def test_a4_the_refusal_is_reachable_on_its_own(tmp_path: Path) -> None:
    """`assert_shadowable` is the control, and it must bind when called
    directly — a check that only exists inside one constructor is one
    refactor away from not existing."""
    with pytest.raises(UnsuppressableSideEffectError):
        assert_shadowable(_mutating_graph(tmp_path / "x"))
    assert_shadowable(_clean_graph())


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a4_the_control_is_load_bearing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the refusal and the mutation reaches the host.

    This is A4's original finding reproduced rather than quoted: the policy
    engine is still in place, still denying every tool call, and the write
    still lands — because it was never a tool call.
    """
    marker = tmp_path / "mutated"

    import aef.harness.shadow as shadow_module

    monkeypatch.setattr(shadow_module, "assert_shadowable", lambda graph: None)

    runner = ShadowRunner(
        incumbent=_clean_graph(), candidate=_mutating_graph(marker), uncontained=True
    )
    observation = runner.observe(_state(), agent_services())

    assert marker.exists(), (
        "the mutating shadow no longer writes, so the refusal above is guarding an attack "
        "that cannot happen and proves nothing"
    )
    assert marker.read_text(encoding="utf-8") == "the shadow mutated production"
    # And the user still got the incumbent's answer, which is exactly why this
    # is dangerous: the damage is invisible in what was served.
    assert observation.state.working_memory["answer"] == "incumbent"
