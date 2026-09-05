"""A7 — reach harness code through `evaluator.suites`.

Trust case §2, reported `held` — and the reason it holds is a hole Milestone
2's adversarial round found and closed: `evaluator.suites` is a list of
`module:function` references the config points at, resolved by import and
CALLED during scoring. A suite of `aef.harness.loop:gate` resolved cleanly.

G0 already forbids agent-authored code importing `aef.harness` and `aef.cli`
— the judging apparatus. `evaluator.suites` was a second door into the same
rooms, reached from a different direction, and `aef.yaml` is a file an
adopter edits by hand.

The forbidden list is READ FROM G0 rather than copied, so the mutation here is
the honest one: point the resolver at an empty forbidden list and watch
`aef.harness.loop:gate` resolve into a callable the evaluator would run.
"""

from __future__ import annotations

import pytest

from aef.config.domain_gates import DomainGateError, build_domain_gates
from aef.config.schema import EvaluatorConfig

HARNESS_SUITE = "aef.harness.loop:gate"
CLI_SUITE = "aef.cli.loop:main"


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reference", [HARNESS_SUITE, CLI_SUITE])
def test_a7_a_suite_naming_the_judging_apparatus_is_refused(reference: str) -> None:
    with pytest.raises(DomainGateError, match="judging apparatus"):
        build_domain_gates(EvaluatorConfig(suites=[reference]))


@pytest.mark.parametrize(
    "reference",
    [
        "aef.harness:anything",
        "aef.harness.gates.g3_improvement:G3Improvement",
        "aef.cli.adopt:run_adopt",
    ],
)
def test_a7_a_submodule_of_the_apparatus_is_refused_too(reference: str) -> None:
    """Prefix matching, not exact matching. A refusal that only names the top
    package is one dotted path away from useless."""
    with pytest.raises(DomainGateError, match="judging apparatus"):
        build_domain_gates(EvaluatorConfig(suites=[reference]))


def test_a7_a_lookalike_package_is_not_collateral_damage() -> None:
    """The control for the control: `aef.harnessing` merely starts with the
    forbidden string. If the refusal fired on it, the rule would be a prefix
    match on text rather than on the package boundary — and an adopter's own
    module could be refused for its name."""
    with pytest.raises(DomainGateError) as excinfo:
        build_domain_gates(EvaluatorConfig(suites=["aef.harnessing:gate"]))
    assert "judging apparatus" not in str(excinfo.value)
    assert "cannot import" in str(excinfo.value)


def test_a7_the_forbidden_list_is_g0s_and_not_a_second_copy() -> None:
    """Two lists of what counts as the apparatus drifting apart is the ADR
    0091 shape, and this pair had already drifted once."""
    from aef.config.domain_gates import _forbidden_prefixes
    from aef.harness.gates.g0_static_safety import FORBIDDEN_AEF_SUBPACKAGES

    assert tuple(_forbidden_prefixes()) == tuple(FORBIDDEN_AEF_SUBPACKAGES)


def test_a7_an_unresolvable_suite_raises_rather_than_being_skipped() -> None:
    """The adjacent failure this module exists to prevent: a suite an owner
    wrote and the evaluator silently ignored. "Ignored because unresolvable"
    would be no improvement on "ignored because unwired"."""
    with pytest.raises(DomainGateError):
        build_domain_gates(EvaluatorConfig(suites=["no.such.module:gate"]))


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a7_the_control_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty the forbidden list and `aef.harness.loop:gate` resolves into a
    callable domain gate — the exact finding Milestone 2's round reported.

    Nothing else is changed: the same config, the same resolver, the same
    import. What is removed is the four-line prefix check.
    """
    import aef.config.domain_gates as domain_gates

    monkeypatch.setattr(domain_gates, "_forbidden_prefixes", lambda: ())

    gates = domain_gates.build_domain_gates(EvaluatorConfig(suites=[HARNESS_SUITE]))
    assert HARNESS_SUITE in gates, (
        "the harness reference no longer resolves at all, so the refusal above is guarding "
        "an import that would fail anyway and proves nothing about the check"
    )
    assert callable(gates[HARNESS_SUITE])

    monkeypatch.undo()
    with pytest.raises(DomainGateError, match="judging apparatus"):
        build_domain_gates(EvaluatorConfig(suites=[HARNESS_SUITE]))
