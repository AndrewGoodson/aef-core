"""A2 — forge a release manifest under a guessed key.

Trust case §2, reported `held`. The attacker has the manifest (it is not a
secret: it names the graph, the commits, the gates and the approver) and wants
a signature the owner's verifier accepts. Two routes are attempted here:

  * sign under a key of the attacker's own choosing, and
  * hand the verifier a manifest with no signature at all, hoping absence is
    treated as a weaker approval rather than as none.

The second is the one worth constructing: ADR 0087's hole was a forger who
rebuilt a *consistent* chain, so "the fields agree with each other" must never
be what verification means.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aef.harness.release import (
    ReleaseError,
    ReleaseManifest,
    SignatureError,
    SigningKey,
    sign,
    verify,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
OWNER_KEY = SigningKey(material=b"owner-key-exactly-32-bytes-long!")
ATTACKER_KEY = SigningKey(material=b"attacker-key-32-bytes-long-here!")


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


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a2_a_manifest_signed_under_the_attackers_key_is_refused() -> None:
    forged = _manifest(approved_by="attacker@example.com")
    signature = sign(forged, ATTACKER_KEY)
    with pytest.raises(SignatureError, match="different key|does not match"):
        verify(forged, signature, OWNER_KEY)


def test_a2_an_unsigned_manifest_is_not_a_weaker_approval() -> None:
    """The cheapest forgery is the empty string."""
    with pytest.raises(SignatureError, match="not an approval"):
        verify(_manifest(), "", OWNER_KEY)


def test_a2_a_manifest_that_evidences_nothing_cannot_even_be_built() -> None:
    """An unevidenced approval is the signature a forger actually wants:
    valid, and about nothing. Refused at construction, before any key."""
    with pytest.raises(ReleaseError, match="evidence"):
        _manifest(evidence={})


def test_a2_a_failing_gate_smuggled_in_behind_a_kept_signature_is_refused() -> None:
    """The evidence is IN the signed payload (ADR 0087), so keeping a valid
    signature and swapping the gate outcomes does not survive."""
    signature = sign(_manifest(), OWNER_KEY)
    with pytest.raises(SignatureError, match="does not match"):
        verify(
            _manifest(evidence={"G0": "pass", "G3": "fail"}, override_reason="waived"),
            signature,
            OWNER_KEY,
        )


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a2_the_control_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the constant-time comparison's verdict — the one line that says
    "this signature is not this manifest's" — and the forgery lands.

    Patched at `hmac.compare_digest` as `release` resolved it, which is the
    narrowest possible edit: everything else about the manifest, the payload
    and the key stays exactly as shipped, so what the attack then succeeds
    against is the real code minus one comparison.
    """
    forged = _manifest(approved_by="attacker@example.com")
    signature = sign(forged, ATTACKER_KEY)

    import aef.harness.release as release

    monkeypatch.setattr(release.hmac, "compare_digest", lambda a, b: True)
    verify(forged, signature, OWNER_KEY)  # the forgery is now accepted

    # And with the control back, the same call refuses. Asserted here rather
    # than relying on the previous tests: a mutation that leaked would make
    # every test in this file pass for the wrong reason.
    monkeypatch.undo()
    with pytest.raises(SignatureError):
        verify(forged, signature, OWNER_KEY)


def test_a2_the_evidence_check_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """And the construction-time refusal: without it, an approval about
    nothing is buildable and signs cleanly."""
    with pytest.raises(ReleaseError):
        _manifest(evidence={})

    monkeypatch.setattr(ReleaseManifest, "__post_init__", lambda self: None)
    hollow = _manifest(evidence={})
    verify(hollow, sign(hollow, OWNER_KEY), OWNER_KEY)
    assert hollow.evidence == {}, "the mutation did not actually produce an unevidenced manifest"
