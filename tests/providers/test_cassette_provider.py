"""`CassetteProvider` (ADR 0123): recorded completions replayed by request
key; a miss fails or goes live, never silently. Every test uses a fake inner
provider; no process is spawned."""

from __future__ import annotations

from pathlib import Path

import pytest

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
    ProviderMessage,
)
from aef.providers.cassette_provider import (
    CassetteError,
    CassetteProvider,
    RecordedCall,
    request_key,
)

REPO = Path(__file__).resolve().parents[2]


class _Counting(ModelProvider):
    name = "counting"

    def __init__(self, reply: str = "answer") -> None:
        self.calls: list[CompletionRequest] = []
        self.reply = reply

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls.append(request)
        return CompletionResult(
            content=f"{self.reply} #{len(self.calls)}",
            model="fake-1",
            input_tokens=3,
            output_tokens=2,
            stop_reason="end_turn",
        )


class _Forbidden(ModelProvider):
    """Raises if anything reaches it: the proof that a hit stays local."""

    name = "forbidden"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise AssertionError("the inner provider was called on a cassette hit")


def _request(text: str = "hello", **overrides: object) -> CompletionRequest:
    fields: dict[str, object] = {
        "messages": (
            ProviderMessage(role="system", content="be terse"),
            ProviderMessage(role="user", content=text),
        ),
        "model": "",
    }
    fields.update(overrides)
    return CompletionRequest(**fields)  # type: ignore[arg-type]


def _recorded(text: str = "hello", reply: str = "recorded reply") -> RecordedCall:
    return RecordedCall.of(
        _request(text),
        CompletionResult(content=reply, model="fake-1", input_tokens=1, output_tokens=1),
    )


# ---------------------------------------------------------------------------
# Hit / miss semantics
# ---------------------------------------------------------------------------
def test_a_hit_returns_the_recorded_result_and_never_calls_inner() -> None:
    provider = CassetteProvider(_Forbidden(), [_recorded()], on_miss="live")
    result = provider.complete(_request())
    assert result.content == "recorded reply"
    assert (provider.hits, provider.misses) == (1, 0)


def test_a_miss_under_fail_raises_naming_the_miss() -> None:
    inner = _Counting()
    provider = CassetteProvider(inner, [_recorded("hello")], on_miss="fail")
    with pytest.raises(ModelProviderError, match="cassette miss"):
        provider.complete(_request("something the recording never saw"))
    assert inner.calls == [], "on_miss='fail' must not fall through to the inner provider"
    assert (provider.hits, provider.misses) == (0, 1)


def test_a_miss_under_live_calls_inner_and_records_it() -> None:
    inner = _Counting()
    provider = CassetteProvider(inner, on_miss="live")
    first = provider.complete(_request("q"))
    second = provider.complete(_request("q"))
    assert len(inner.calls) == 1, "the second identical request is a hit"
    assert first.content == second.content == "answer #1"
    assert [c.result.content for c in provider.recorded] == ["answer #1"]
    assert (provider.hits, provider.misses) == (1, 1)


def test_a_miss_under_live_with_no_inner_provider_fails_naming_the_absence() -> None:
    provider = CassetteProvider(None, on_miss="live")
    with pytest.raises(ModelProviderError, match="no live provider"):
        provider.complete(_request())


def test_on_miss_is_validated_at_construction() -> None:
    with pytest.raises(ValueError, match="on_miss"):
        CassetteProvider(None, on_miss="maybe")


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------
def test_key_covers_messages_model_and_max_tokens_only() -> None:
    base = _request("hello")
    assert request_key(base) == request_key(_request("hello"))
    assert request_key(base) != request_key(_request("hello!"))
    assert request_key(base) != request_key(_request("hello", model="other"))
    assert request_key(base) != request_key(_request("hello", max_tokens=5))
    # Not in the key: the Anthropic adapter does not forward temperature and
    # metadata is telemetry. Two requests differing only there are one question.
    assert request_key(base) == request_key(_request("hello", temperature=0.2))
    assert request_key(base) == request_key(_request("hello", metadata={"trace": "x"}))


def test_key_distinguishes_role_of_the_same_text() -> None:
    as_user = CompletionRequest(messages=(ProviderMessage(role="user", content="x"),), model="")
    as_system = CompletionRequest(messages=(ProviderMessage(role="system", content="x"),), model="")
    assert request_key(as_user) != request_key(as_system)


# ---------------------------------------------------------------------------
# Payload round-trip
# ---------------------------------------------------------------------------
def test_recorded_call_round_trips_through_its_payload() -> None:
    call = _recorded("hello", "reply")
    payload = call.to_payload()
    assert payload["key"] == call.key
    assert RecordedCall.from_payload(payload) == call
    assert RecordedCall.from_payload(payload).key == call.key


def test_a_hand_edited_key_is_refused() -> None:
    payload = _recorded().to_payload()
    payload["key"] = "0" * 64
    with pytest.raises(CassetteError, match="does not match its request"):
        RecordedCall.from_payload(payload)


def test_a_malformed_payload_fails_as_a_cassette_error() -> None:
    with pytest.raises(CassetteError):
        RecordedCall.from_payload({"request": {}, "result": {}})
    with pytest.raises(CassetteError, match="role"):
        RecordedCall.from_payload(
            {
                "request": {
                    "messages": [{"role": "narrator", "content": "x"}],
                    "model": "",
                    "max_tokens": 1,
                },
                "result": {"content": "", "model": "", "input_tokens": 0, "output_tokens": 0},
            }
        )


# ---------------------------------------------------------------------------
# Vendor isolation: it is a wrapper, not an adapter
# ---------------------------------------------------------------------------
def test_the_cassette_imports_no_vendor_sdk() -> None:
    from tests.test_vendor_isolation import _find_violations

    assert _find_violations(REPO / "aef" / "providers" / "cassette_provider.py") == []
