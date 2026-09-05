"""A5 — a shadow node that does file I/O directly, making no tool call.

Trust case §2, reported **BROKE IT**, and the only attack in the round that
was a *demonstrated bypass* rather than an argument. The candidate imports
`pathlib` and writes. The suppression is `PolicyEngine` with an empty scope
set, which denies tool calls; there is no tool call to deny.

The fix (ADR 0105/0161/0173) is containment, and it is the DEFAULT: with no
container runtime and no image, `ContainmentMode.AUTO` **refuses to run the
shadow at all** rather than falling back to the in-process path. So the attack
is stopped by a refusal here, with no Docker required.

The mutation is the owner's opt-out, `ContainmentMode.OFF`, which is exactly
what the trust case reports as still real: the bypass is not gone, it is
behind a written decision that is announced and ledgered.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from aef.cli.run import build_run_config
from aef.harness.ledger import EventKind, read
from aef.harness.shadow import (
    ContainmentMode,
    UncontainedShadowError,
    shadow_for,
)
from aef.kernel import END, Graph, Node
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta


def _escaping_graph(marker: Path) -> Graph:
    """The hostile candidate. No tool call anywhere in it."""

    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("the shadow wrote this to the host", encoding="utf-8")
        return StateDelta(), END

    return Graph(
        id="c",
        version="1",
        nodes={"work": Node(id="work", version="1", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )


def _clean_graph() -> Graph:
    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(), END

    return Graph(
        id="i",
        version="1",
        nodes={"work": Node(id="work", version="1", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )


def _host_marker() -> Path:
    """Deliberately OUTSIDE any tmp_path the harness might mount: the question
    is whether the candidate reached the host, not whether it reached its own
    workspace."""
    return Path(tempfile.mkdtemp()) / "a5_shadow_did_io"


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a5_the_default_refuses_to_run_the_escaping_candidate_at_all(tmp_path: Path) -> None:
    """`auto` with no runtime and no image is a refusal, not a fallback. The
    candidate never executes, so the host is never touched."""
    marker = _host_marker()
    with pytest.raises(UncontainedShadowError):
        shadow_for(
            _clean_graph(),
            entrypoint="unused:build_graph",
            workdir=tmp_path,
            image=None,
            mode=ContainmentMode.AUTO,
            in_process_candidate=_escaping_graph(marker),
        )
    assert not marker.exists(), "the shadow ran before refusing"


def test_a5_the_config_default_is_the_one_that_refuses(tmp_path: Path) -> None:
    """And `auto` is what an `aef.yaml` that says nothing resolves to — the
    refusal is the default an adopter gets, not a mode they must choose.
    Read through the config path (ADR 0173) rather than spelled here, so the
    two cannot drift."""
    marker = _host_marker()
    with pytest.raises(UncontainedShadowError):
        shadow_for(
            _clean_graph(),
            entrypoint="unused:build_graph",
            workdir=tmp_path,
            image=None,
            mode=build_run_config(None).containment_mode,
            in_process_candidate=_escaping_graph(marker),
        )
    assert not marker.exists()


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a5_the_control_is_load_bearing(tmp_path: Path) -> None:
    """Set containment `off` — the owner's written opt-out — and A5 lands
    exactly as the trust case reports it.

    This is the mutation AND the honest half of §2.1: the bypass is still
    real. What changed is that reaching it requires an owner to write
    `shadow.containment: off`, and that the resulting evidence is stamped as
    uncontained in the ledger so nobody reads it without knowing what it cost.
    """
    marker = _host_marker()
    announced: list[str] = []

    shadow = shadow_for(
        _clean_graph(),
        entrypoint="unused:build_graph",
        workdir=tmp_path,
        image="aef-worker:test",
        mode=ContainmentMode.OFF,
        in_process_candidate=_escaping_graph(marker),
        ledger_root=tmp_path,
        proposal_id="a5-red-team",
        warn=announced.append,
    )
    observation = shadow.runner.observe(
        AEFState(run_id="r", agent_id="a", objective="o"), agent_services()
    )

    assert marker.exists(), (
        "the in-process shadow no longer escapes: A5 is no longer a demonstrable bypass, "
        "so the refusal tested above is guarding nothing and §2.1 of the trust case is stale"
    )
    assert observation.contained is False
    assert announced and "OFF by owner choice" in announced[0], "the opt-out was silent"

    (entry,) = read(tmp_path)
    assert entry.kind is EventKind.CONTAINMENT
    assert entry.detail["security_event"] is True
    assert entry.detail["containment"]["owner_opted_out"] is True
