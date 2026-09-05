"""A6 — choose a tenant tag that evades the candidate arm.

Trust case §2.3. Reported as a break, then **withdrawn as a mislabelling** —
1% of tenants staying on the incumbent at 99% exposure is correct behaviour,
not an escape. The real weakness underneath it was demonstrated and is the one
attacked here: assignment used to be a *public deterministic hash of a string
the tenant supplies*, so a tenant that controls its own tag could search
offline for the arm it wanted. The document's number:

    tried 200 candidate tags at 99% exposure -> 1 lands on the incumbent: ['evader-106']

The fix (ADR 0106) keys the hash with an owner-held `CanarySalt`. What that
buys is precise and is asserted precisely: it removes OFFLINE computation. It
does not remove online probing, and this module refuses to claim it does.

The attack, therefore, is the realistic one: the attacker runs the *public*
function — the one it can evaluate — picks the tags it predicts land on the
incumbent, and then those tags are assigned by the owner's *keyed* function.
The control holds if the attacker's prediction is worth no more than chance.
"""

from __future__ import annotations

import pytest

from aef.harness.canary import (
    CanaryError,
    CanarySalt,
    CanaryState,
    assigned_to_candidate,
)

GRAPH = "demo_agent"
VERSION = 2
EXPOSURE = 99
OWNER_SALT = CanarySalt(material=b"owner-held-salt-exactly-32-byte!")
TAGS = tuple(f"evader-{i}" for i in range(400))


def _predicted_evaders() -> tuple[str, ...]:
    """What the attacker computes with no salt: the tags the PUBLIC function
    says stay on the incumbent at 99% exposure."""
    return tuple(
        tag
        for tag in TAGS
        if not assigned_to_candidate(tag, graph_id=GRAPH, version=VERSION, percent=EXPOSURE)
    )


def _actually_on_incumbent(tags: tuple[str, ...]) -> tuple[str, ...]:
    """What those tags do under the OWNER's keyed function."""
    return tuple(
        tag
        for tag in tags
        if not assigned_to_candidate(
            tag, graph_id=GRAPH, version=VERSION, percent=EXPOSURE, salt=OWNER_SALT
        )
    )


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a6_the_offline_search_finds_evaders_in_the_unkeyed_function(
    attack_log: list[str],
) -> None:
    """First, the attack must be viable at all. This is §2.3's reproduction:
    an unsalted assignment is a public function of a tenant-chosen string, and
    searching it finds the arm you want."""
    predicted = _predicted_evaders()
    attack_log.append(f"unkeyed: {len(predicted)} of {len(TAGS)} tags predicted to evade")
    assert predicted, "the offline search found nothing, so this attack is not reproduced"


def test_a6_the_offline_search_does_not_transfer_to_the_keyed_assignment(
    attack_log: list[str],
) -> None:
    """The control. The attacker's shortlist must be worth no more than a
    random shortlist of the same size — roughly 1% of it lands on the
    incumbent at 99% exposure, which is the base rate, not an evasion.
    """
    predicted = _predicted_evaders()
    landed = _actually_on_incumbent(predicted)
    rate = len(landed) / len(predicted)
    attack_log.append(
        f"keyed: {len(landed)} of {len(predicted)} predicted evaders actually evade "
        f"({rate:.1%}); base rate at {EXPOSURE}% exposure is {100 - EXPOSURE}%"
    )
    # Generous by an order of magnitude: chance is 1%, and anything under 10%
    # is unambiguously "the search bought nothing". A tight bound here would
    # make the test a flake about one salt's arithmetic rather than a claim
    # about the control.
    assert rate < 0.10, attack_log


def test_a6_an_unkeyed_canary_cannot_be_constructed_by_accident() -> None:
    """The second half of the fix: a rollout must SAY it is unkeyed. A default
    that silently ran unkeyed would leave the offline search live in every
    deployment that never read the ADR."""
    with pytest.raises(CanaryError):
        CanaryState(graph_id=GRAPH, candidate_version=VERSION, warm_version=1)

    keyed = CanaryState(graph_id=GRAPH, candidate_version=VERSION, warm_version=1, salt=OWNER_SALT)
    assert keyed.salt is not None


def test_a6_an_untagged_request_is_refused_rather_than_defaulted() -> None:
    """The other way to evade: send no tag at all. Defaulting an unlabelled
    request to the incumbent would silently exempt whoever forgot one."""
    with pytest.raises(CanaryError, match="empty tag"):
        assigned_to_candidate("", graph_id=GRAPH, version=VERSION, percent=EXPOSURE)


def test_a6_two_spellings_of_one_tenant_land_in_one_arm() -> None:
    """The weakness attacking the fix found: NFC and NFD of the same tenant
    name are different bytes. One tenant in two arms contributes samples to
    both, which is what stratifying by tenant exists to prevent."""
    nfc, nfd = "café-corp", "café-corp"
    assert nfc != nfd
    both = {
        assigned_to_candidate(tag, graph_id=GRAPH, version=VERSION, percent=50, salt=OWNER_SALT)
        for tag in (nfc, nfd)
    }
    assert len(both) == 1, "one tenant landed in two arms under two Unicode spellings"


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a6_the_control_is_load_bearing(attack_log: list[str]) -> None:
    """Take the salt away — nothing else — and the attacker's offline
    shortlist becomes a perfect oracle.

    That is the whole content of the fix, measured rather than asserted: with
    a key, the prediction is worth chance; without one, it is worth 100%.
    """
    predicted = _predicted_evaders()
    unkeyed_landed = tuple(
        tag
        for tag in predicted
        if not assigned_to_candidate(tag, graph_id=GRAPH, version=VERSION, percent=EXPOSURE)
    )
    attack_log.append(
        f"control removed: {len(unkeyed_landed)} of {len(predicted)} predicted evaders "
        f"actually evade (100% expected)"
    )
    assert len(unkeyed_landed) == len(predicted), attack_log
    assert predicted, "nothing to predict, so the mutation demonstrates nothing"

    # And the mutation is strictly worse than the control, on the same tags.
    assert len(_actually_on_incumbent(predicted)) < len(unkeyed_landed)
