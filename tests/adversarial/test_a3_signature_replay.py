"""A3 — replay a valid signature onto another commit.

Trust case §2, reported `held`. This is the attack that needs no key at all.
The owner has already signed *something*; the attacker keeps that signature
byte for byte and changes what it is about — a different head commit, a
different approver, a different version. It is the cheapest promotion forgery
there is, because everything it needs is public.

The control is that all of those fields are inside `ReleaseManifest.payload()`,
the exact bytes the HMAC covers. The mutation removes `head_sha` from that
payload and shows the replay landing: a signature over a promotion that does
not name the commit it promotes is a signature over any commit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from aef.harness.release import (
    ReleaseError,
    ReleaseManifest,
    SignatureError,
    SignedRelease,
    SigningKey,
    sign,
    verify,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
KEY = SigningKey(material=b"owner-key-exactly-32-bytes-long!")

APPROVED_HEAD = "b" * 40
ATTACKER_HEAD = "c" * 40


def _manifest(**kw: object) -> ReleaseManifest:
    base: dict[str, object] = {
        "graph_id": "demo_agent",
        "version": 3,
        "base_sha": "a" * 40,
        "head_sha": APPROVED_HEAD,
        "evidence": {"G0": "pass", "G3": "pass"},
        "approved_by": "owner@example.com",
        "approved_at": NOW,
    }
    base.update(kw)
    return ReleaseManifest(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a3_a_signature_does_not_transfer_to_another_commit() -> None:
    stolen = sign(_manifest(), KEY)
    with pytest.raises(SignatureError, match="does not match"):
        verify(_manifest(head_sha=ATTACKER_HEAD), stolen, KEY)


def test_a3_a_signature_does_not_transfer_to_another_approver() -> None:
    stolen = sign(_manifest(), KEY)
    with pytest.raises(SignatureError):
        verify(_manifest(approved_by="attacker@example.com"), stolen, KEY)


def test_a3_a_signature_does_not_transfer_to_another_version() -> None:
    stolen = sign(_manifest(), KEY)
    with pytest.raises(SignatureError):
        verify(_manifest(version=4), stolen, KEY)


def test_a3_a_replay_through_the_serialised_envelope_is_refused() -> None:
    """The realistic delivery: the attacker edits the JSON file, not the
    dataclass. `SignedRelease.from_payload` must rebuild the manifest and
    re-verify rather than trust the envelope's own claim."""
    envelope = SignedRelease(manifest=_manifest(), signature=sign(_manifest(), KEY)).to_payload()
    tampered: dict[str, Any] = json.loads(json.dumps(envelope))
    tampered["manifest"]["head_sha"] = ATTACKER_HEAD

    rebuilt = SignedRelease.from_payload(tampered)
    assert rebuilt.manifest.head_sha == ATTACKER_HEAD
    with pytest.raises(SignatureError):
        verify(rebuilt.manifest, rebuilt.signature, KEY)


def test_a3_a_no_op_promotion_cannot_be_signed_at_all() -> None:
    """Belt and braces on the same attack from the other end: a manifest whose
    head equals its base promotes nothing, so its signature would be one
    waiting to be re-pointed. Refused at construction."""
    with pytest.raises(ReleaseError, match="no change to promote"):
        _manifest(head_sha="a" * 40)


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a3_the_control_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop `head_sha` from the signed payload — nothing else — and the same
    stolen signature verifies against the attacker's commit.

    This is the honest form of "the commit is bound by the signature": the
    binding is the payload's contents, and removing one key from it is enough
    to make a promotion transferable.
    """
    original = ReleaseManifest.payload

    def payload_without_the_commit(self: ReleaseManifest) -> bytes:
        body = json.loads(original(self))
        body.pop("head_sha")
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    monkeypatch.setattr(ReleaseManifest, "payload", payload_without_the_commit)

    stolen = sign(_manifest(), KEY)
    verify(_manifest(head_sha=ATTACKER_HEAD), stolen, KEY)  # the replay now lands

    monkeypatch.undo()
    with pytest.raises(SignatureError):
        verify(_manifest(head_sha=ATTACKER_HEAD), sign(_manifest(), KEY), KEY)
