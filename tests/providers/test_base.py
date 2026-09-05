import pytest

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    FallbackProvider,
    ModelProvider,
    ModelProviderError,
    ProviderMessage,
    validate_isolation,
)


class _FailingProvider(ModelProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ModelProviderError(f"{self.name} is down")


class _WorkingProvider(ModelProvider):
    def __init__(self, name: str = "working") -> None:
        self.name = name

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="ok", model=request.model, input_tokens=1, output_tokens=1)


def _request() -> CompletionRequest:
    return CompletionRequest(messages=(ProviderMessage(role="user", content="hi"),), model="m")


def test_fallback_uses_first_working_provider() -> None:
    provider = FallbackProvider([_FailingProvider("primary"), _WorkingProvider("secondary")])
    result = provider.complete(_request())
    assert result.content == "ok"


def test_fallback_raises_when_all_providers_fail() -> None:
    provider = FallbackProvider([_FailingProvider("primary"), _FailingProvider("secondary")])
    with pytest.raises(ModelProviderError, match="primary is down"):
        provider.complete(_request())


def test_fallback_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError):
        FallbackProvider([])


def test_fallback_snapshots_caller_owned_provider_order() -> None:
    providers: list[ModelProvider] = [_WorkingProvider("primary")]
    provider = FallbackProvider(providers)

    providers.clear()

    assert provider.complete(_request()).content == "ok"


def test_fallback_does_not_call_later_providers_once_one_succeeds() -> None:
    calls: list[str] = []

    class _CountingProvider(ModelProvider):
        def __init__(self, name: str) -> None:
            self.name = name

        def complete(self, request: CompletionRequest) -> CompletionResult:
            calls.append(self.name)
            return CompletionResult(
                content=self.name, model=request.model, input_tokens=0, output_tokens=0
            )

    provider = FallbackProvider([_CountingProvider("first"), _CountingProvider("second")])
    result = provider.complete(_request())
    assert result.content == "first"
    assert calls == ["first"]


def test_fallback_tries_a_third_provider_after_two_failures() -> None:
    provider = FallbackProvider(
        [_FailingProvider("primary"), _FailingProvider("secondary"), _WorkingProvider("tertiary")]
    )
    result = provider.complete(_request())
    assert result.content == "ok"


def test_fallback_all_fail_error_names_every_provider_not_just_the_first() -> None:
    provider = FallbackProvider([_FailingProvider("primary"), _FailingProvider("secondary")])
    with pytest.raises(ModelProviderError) as exc_info:
        provider.complete(_request())
    message = str(exc_info.value)
    assert "primary" in message and "primary is down" in message
    assert "secondary" in message and "secondary is down" in message


def test_fallback_does_not_catch_non_model_provider_errors() -> None:
    """A bug in an adapter (a raw exception leaking past the vendor
    boundary, contradicting ModelProvider's own contract) must surface
    immediately, not be silently retried against the next provider as if
    it were an ordinary vendor failure."""

    class _BuggyProvider(ModelProvider):
        name = "buggy"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            raise TypeError("adapter bug: forgot to wrap this in ModelProviderError")

    provider = FallbackProvider([_BuggyProvider(), _WorkingProvider("never_reached")])
    with pytest.raises(TypeError, match="adapter bug"):
        provider.complete(_request())


def test_default_max_tokens_leaves_room_for_thinking() -> None:
    """Current models think before answering and `max_tokens` caps thinking
    plus reply together. The old default of 1024 could be spent entirely on
    thinking, returning `stop_reason == "max_tokens"` and empty text. The
    vendor guide's non-streaming default is ~16000."""
    request = CompletionRequest(messages=(), model="m")
    assert request.max_tokens >= 16000


# ---------------------------------------------------------------------------
# `isolation` — the containment claim, per provider (ADR 0169, F4)
# ---------------------------------------------------------------------------
def test_a_provider_that_has_not_thought_about_it_claims_nothing() -> None:
    """The default is the empty set, not somebody else's guarantees. F4 was
    exactly the opposite arrangement: one sentence about `ClaudeCodeProvider`
    stamped into every generated module as a claim about the path."""

    class _Bare(ModelProvider):
        name = "bare"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(content="", model="", input_tokens=0, output_tokens=0)

    assert _Bare().isolation == frozenset()


def test_an_unknown_property_name_is_refused_rather_than_quietly_dropped() -> None:
    """A typo would otherwise read as a smaller claim than the owner meant."""
    with pytest.raises(ValueError, match="unknown isolation"):
        validate_isolation(["no_tool"])
    with pytest.raises(ValueError, match="must be a list"):
        validate_isolation("no_tools")
    assert validate_isolation(["no_tools", "single_turn"]) == frozenset({"no_tools", "single_turn"})


def test_the_two_channel_properties_are_mutually_exclusive() -> None:
    """A system message travels in one channel or the other."""
    with pytest.raises(ValueError, match="one channel or the other"):
        validate_isolation(["system_role", "user_turn_persona"])


def test_a_fallback_chain_is_as_isolated_as_its_least_isolated_member() -> None:
    """Intersection, not union or first-wins. The primary failing is exactly
    when the fallback runs, so a property the fallback does not enforce was
    never enforced for that call."""

    class _Fixed(ModelProvider):
        def __init__(self, name: str, props: frozenset[str]) -> None:
            self.name = name
            self._props = props

        @property
        def isolation(self) -> frozenset[str]:
            return self._props

        def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(content="", model="", input_tokens=0, output_tokens=0)

    strong = _Fixed("strong", frozenset({"no_tools", "single_turn", "system_role"}))
    weak = _Fixed("weak", frozenset({"single_turn"}))
    assert FallbackProvider([strong, weak]).isolation == frozenset({"single_turn"})
    # An uncharacterised member costs the chain every claim it had.
    unknown = _Fixed("unknown", frozenset())
    assert FallbackProvider([strong, unknown]).isolation == frozenset()


def test_total_input_tokens_is_the_whole_context_and_input_tokens_is_not() -> None:
    """ADR 0126's numbers live in the cache counters, which `CompletionResult`
    did not keep. `input_tokens` was 2 on the calls that produced them."""
    result = CompletionResult(
        content="OK",
        model="m",
        input_tokens=2,
        output_tokens=4,
        cache_read_input_tokens=4_600,
        cache_creation_input_tokens=82,
    )
    assert result.total_input_tokens == 4_684
    # Defaults keep every older construction meaning what it meant.
    plain = CompletionResult(content="OK", model="m", input_tokens=17, output_tokens=1)
    assert plain.total_input_tokens == 17
    assert plain.model_attribution == "requested"
