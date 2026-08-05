"""Closing trust case §2.3: the keyed tenant hash.

Unkeyed, `assigned_to_candidate` is a public deterministic function of a
string the tenant supplies, so a tenant controlling its own tag can compute
which arm any tag lands in and pick one — biasing exactly the evidence
promotion is read from. Demonstrated there: one in roughly two hundred tried
tags landed on the incumbent at 99% exposure, found by searching offline.

**What keying buys is bounded, and the bound is tested here too.** It removes
OFFLINE computation. It does not remove online probing by a tenant that can
observe which arm it landed in and re-register. Claiming otherwise would be
the overclaim this program has recorded four ADRs about.
"""

from pathlib import Path

import pytest

from aef.harness.canary import (
    MAX_SALT_BYTES,
    MIN_SALT_BYTES,
    CanaryError,
    CanarySalt,
    CanaryState,
    UnkeyedCanaryError,
    assigned_to_candidate,
)

SALT = CanarySalt(material=b"canary-salt-for-tests-32-bytes!!")
OTHER = CanarySalt(material=b"a-different-salt-also-32-bytes!!!")
TAGS = [f"tenant-{i}" for i in range(4000)]


def _admitted(percent: int, salt: CanarySalt | None, version: int = 1) -> set[str]:
    return {
        t
        for t in TAGS
        if assigned_to_candidate(t, graph_id="g", version=version, percent=percent, salt=salt)
    }


# --------------------------------------------------------------------------
# The property the key adds
# --------------------------------------------------------------------------


def test_a_different_salt_assigns_a_different_population() -> None:
    """The whole point. Without this the key is decoration."""
    assert _admitted(25, SALT) != _admitted(25, OTHER)


def test_the_unkeyed_assignment_is_computable_by_anyone() -> None:
    """The control, and the vulnerability. Reproduced from the trust case: a
    tenant that knows the algorithm can sift tags before choosing one, because
    the function needs nothing it does not have."""
    from hashlib import blake2b

    tag = "tenant-42"
    seed = f"g:1:{tag}".encode()
    attacker = int.from_bytes(blake2b(seed, digest_size=8).digest(), "big") % 100 < 25
    assert attacker == assigned_to_candidate(tag, graph_id="g", version=1, percent=25)


def test_a_tenant_without_the_salt_cannot_reproduce_the_keyed_assignment() -> None:
    """The same computation, run without the key, disagrees. It is not that
    the attacker gets a wrong answer for one tag — it is that it has no better
    than chance across many."""
    from hashlib import blake2b

    agreements = 0
    for tag in TAGS[:500]:
        seed = f"g:1:{tag}".encode()
        guess = int.from_bytes(blake2b(seed, digest_size=8).digest(), "big") % 100 < 25
        if guess == assigned_to_candidate(tag, graph_id="g", version=1, percent=25, salt=SALT):
            agreements += 1
    # Two independent 25% predicates agree ~62.5% of the time by chance
    # (0.25*0.25 + 0.75*0.75). Anything near 100% would mean the salt was not
    # reaching the digest at all.
    assert 0.5 < agreements / 500 < 0.75, agreements / 500


def test_online_probing_is_still_possible_and_that_is_stated() -> None:
    """The bound on what keying buys.

    A tenant that can OBSERVE its arm can still re-register under new tags
    until it lands where it wants — keying makes that one tag at a time and
    visible in whatever issues tags, instead of instant and offline. Asserted
    so the limitation cannot quietly become a claim of unpredictability.
    """
    wanted = [
        t
        for t in TAGS
        if not assigned_to_candidate(t, graph_id="g", version=1, percent=99, salt=SALT)
    ]
    assert wanted, "at 99% exposure some tags still land on the incumbent, by construction"


# --------------------------------------------------------------------------
# The properties the key must not break
# --------------------------------------------------------------------------


def test_assignment_stays_monotone_under_a_salt() -> None:
    """The requirement advancing a stage depends on: a tenant admitted at 5%
    is still admitted at 25%, so the ladder accumulates evidence instead of
    reshuffling it."""
    previous: set[str] = set()
    for percent in (1, 5, 25, 50, 100):
        admitted = _admitted(percent, SALT)
        assert previous <= admitted, f"tenants dropped out of the candidate arm at {percent}%"
        previous = admitted
    assert previous == set(TAGS)


def test_the_salt_does_not_skew_the_split() -> None:
    for percent in (1, 25, 50):
        share = len(_admitted(percent, SALT)) / len(TAGS)
        assert abs(share - percent / 100) < 0.03, f"{percent}% target produced {share:.3f}"


def test_assignment_stays_stable_for_a_tenant_under_a_salt() -> None:
    first = assigned_to_candidate("tenant-7", graph_id="g", version=2, percent=25, salt=SALT)
    for _ in range(50):
        assert (
            assigned_to_candidate("tenant-7", graph_id="g", version=2, percent=25, salt=SALT)
            is first
        )


def test_a_new_version_still_reshuffles_under_the_same_salt() -> None:
    assert _admitted(10, SALT, version=1) != _admitted(10, SALT, version=2)


# --------------------------------------------------------------------------
# Keyed by default
# --------------------------------------------------------------------------


def test_a_rollout_without_a_salt_is_refused() -> None:
    with pytest.raises(UnkeyedCanaryError, match="self-selectable"):
        CanaryState(graph_id="g", candidate_version=2, warm_version=1)


def test_the_refusal_names_the_way_out() -> None:
    try:
        CanaryState(graph_id="g", candidate_version=2, warm_version=1)
    except UnkeyedCanaryError as exc:
        message = str(exc)
    assert "CanarySalt.from_file" in message
    assert "unkeyed=True" in message


def test_claiming_both_at_once_is_refused() -> None:
    with pytest.raises(CanaryError, match="one of the two is a mistake"):
        CanaryState(graph_id="g", candidate_version=2, warm_version=1, salt=SALT, unkeyed=True)


def test_opting_out_is_recorded_on_the_rollout() -> None:
    """An unkeyed rollout must not be indistinguishable from a keyed one —
    the same reasoning as `SandboxCapabilities` (ADR 0102)."""
    unkeyed = CanaryState(graph_id="g", candidate_version=2, warm_version=1, unkeyed=True)
    assert not unkeyed.keyed
    assert unkeyed.salt_fingerprint == "unkeyed"

    keyed = CanaryState(graph_id="g", candidate_version=2, warm_version=1, salt=SALT)
    assert keyed.keyed
    assert keyed.salt_fingerprint != "unkeyed"


def test_changing_the_salt_mid_rollout_is_caught() -> None:
    """Reshuffling every tenant silently discards the samples gathered so far
    while the stage index goes on claiming they accumulated — the failure the
    monotonicity requirement exists to prevent, arriving by the back door."""
    before = CanaryState(graph_id="g", candidate_version=2, warm_version=1, salt=SALT)
    after = CanaryState(
        graph_id="g", candidate_version=2, warm_version=1, salt=OTHER, stage_index=2
    )
    after.assert_same_population(after.salt_fingerprint)  # the control: same salt, no raise
    with pytest.raises(CanaryError, match="reshuffled"):
        after.assert_same_population(before.salt_fingerprint)


def test_the_fingerprint_is_not_the_salt() -> None:
    state = CanaryState(graph_id="g", candidate_version=2, warm_version=1, salt=SALT)
    assert SALT.material.hex() not in state.salt_fingerprint
    assert len(state.salt_fingerprint) < len(SALT.material.hex())


# --------------------------------------------------------------------------
# The salt itself
# --------------------------------------------------------------------------


def test_a_short_salt_is_refused() -> None:
    with pytest.raises(CanaryError, match=str(MIN_SALT_BYTES)):
        CanarySalt(material=b"too-short")


def test_a_salt_longer_than_blake2b_accepts_is_refused() -> None:
    with pytest.raises(CanaryError):
        CanarySalt(material=b"x" * (MAX_SALT_BYTES + 1))


def test_a_world_readable_salt_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "salt"
    path.write_bytes(b"s" * 32)
    path.chmod(0o644)
    with pytest.raises(CanaryError, match="accessible"):
        CanarySalt.from_file(path)

    path.chmod(0o600)
    assert CanarySalt.from_file(path).material == b"s" * 32


def test_the_salt_never_appears_in_a_repr() -> None:
    """A salt in a traceback is a salt in a log, and a logged salt is a
    population a tenant can compute."""
    assert SALT.material not in repr(SALT).encode()
    assert "material" not in repr(SALT)


def test_the_salt_is_not_the_signing_key() -> None:
    """Reusing one secret for two purposes means a compromise of either leaks
    both, and the release key is held by a person while this one is read by a
    running service."""
    from aef.harness.release import SigningKey

    assert CanarySalt is not SigningKey
    assert not isinstance(SALT, SigningKey)


# --------------------------------------------------------------------------
# The adversarial round on the keying. Two REPRODUCED.
# --------------------------------------------------------------------------


def test_the_fingerprint_is_not_a_cheap_offline_oracle() -> None:
    """REPRODUCED: the fingerprint was a plain `blake2b` of the salt.

    A fingerprint is persisted next to a rollout, so it reaches state files
    and logs — and any deterministic function of the salt is a verification
    oracle: guess a salt, compute, compare. That is unavoidable if restarts
    are to prove they kept the same population, so the answer is to make each
    guess COST, not to pretend the oracle is absent.
    """
    from hashlib import blake2b

    plain = blake2b(SALT.material, digest_size=8).hexdigest()
    assert SALT.fingerprint() != plain, "the fingerprint is a microsecond-per-guess oracle"


def test_each_fingerprint_guess_costs_milliseconds_not_microseconds() -> None:
    """The property, measured rather than assumed from the algorithm name. A
    KDF configured with too few iterations is the same defect with better
    manners."""
    import time

    started = time.perf_counter()
    SALT.fingerprint()
    elapsed = time.perf_counter() - started
    assert elapsed > 0.002, f"a guess costs {elapsed * 1000:.2f}ms — too cheap to slow a search"


def test_the_fingerprint_is_domain_separated() -> None:
    """So it can never be mistaken for, or replayed as, another digest of the
    same salt."""
    from hashlib import pbkdf2_hmac

    from aef.harness.canary import FINGERPRINT_DOMAIN

    assert b"canary" in FINGERPRINT_DOMAIN
    other = pbkdf2_hmac("sha256", SALT.material, b"some-other-domain", 200_000, 8).hex()
    assert SALT.fingerprint() != other


def test_the_same_tenant_encoded_two_ways_gets_one_arm() -> None:
    """REPRODUCED: "café" in NFC and NFD are different byte sequences, so one
    tenant sending each from two clients landed in different arms **52% of the
    time** — seeing inconsistent behaviour AND contributing samples to both
    arms, which is exactly what stratifying by tenant exists to prevent.
    """
    import unicodedata

    disagreements = 0
    names = [f"café-{i}" for i in range(300)] + [f"naïve-{i}" for i in range(300)]
    for name in names:
        nfc = unicodedata.normalize("NFC", name)
        nfd = unicodedata.normalize("NFD", name)
        assert nfc.encode() != nfd.encode(), "the fixture is not exercising two encodings"
        if assigned_to_candidate(
            nfc, graph_id="g", version=1, percent=50, salt=SALT
        ) != assigned_to_candidate(nfd, graph_id="g", version=1, percent=50, salt=SALT):
            disagreements += 1
    assert disagreements == 0, f"{disagreements}/{len(names)} tenants split across both arms"


def test_generate_produces_a_random_salt_of_the_right_size() -> None:
    """The documented way to get a salt. `secrets`, not `random`: a salt from
    a seeded PRNG is one an attacker who learns the seed reproduces."""
    first, second = CanarySalt.generate(), CanarySalt.generate()
    assert first.material != second.material
    assert len(first.material) == MIN_SALT_BYTES


def test_the_boundaries_hold_under_a_salt() -> None:
    """0% must expose nobody and 100% must expose everybody, or a rollout
    either starts before it began or never finishes."""
    assert _admitted(0, SALT) == set()
    assert _admitted(100, SALT) == set(TAGS)


def test_two_graphs_do_not_share_a_population_by_construction() -> None:
    """Checked, and sound: the overlap is chance, not correlation."""
    alpha = {
        t
        for t in TAGS
        if assigned_to_candidate(t, graph_id="alpha", version=1, percent=25, salt=SALT)
    }
    beta = {
        t
        for t in TAGS
        if assigned_to_candidate(t, graph_id="beta", version=1, percent=25, salt=SALT)
    }
    assert 0.18 < len(alpha & beta) / len(alpha) < 0.32
