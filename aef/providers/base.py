"""`ModelProvider` — the stable interface every LLM vendor sits behind.

No vendor SDK is imported here (constraint #3). Concrete adapters
(`aef/providers/anthropic_provider.py`, future openai/gemini/local adapters)
import their vendor SDK and implement this interface; `kernel/` and
`reasoning/` only ever see `ModelProvider`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ProviderMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    messages: tuple[ProviderMessage, ...]
    model: str
    max_tokens: int = 1024
    temperature: float = 1.0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None


class ModelProviderError(RuntimeError):
    """Raised by a provider adapter on any failure (auth, rate limit, network).

    `FallbackProvider` catches this specifically — adapters must not let
    vendor-specific exception types leak past their own module.
    """


class ModelProvider(ABC):
    """One vendor's model surface, reduced to what the reasoning plane needs."""

    name: str

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Synchronous completion call. Raises `ModelProviderError` on failure."""
        raise NotImplementedError


class FallbackProvider(ModelProvider):
    """Tries each provider in order; falls through to the next on
    `ModelProviderError`. This is the vendor-neutrality mechanism (report
    Recommendation #1 / constraint #3): callers depend only on
    `ModelProvider`, never on which vendor actually answered.
    """

    name = "fallback"

    def __init__(self, providers: list[ModelProvider]) -> None:
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider")
        self._providers = providers

    def complete(self, request: CompletionRequest) -> CompletionResult:
        errors: list[tuple[str, Exception]] = []
        for provider in self._providers:
            try:
                return provider.complete(request)
            except ModelProviderError as exc:
                errors.append((provider.name, exc))
        summary = "; ".join(f"{name}: {exc}" for name, exc in errors)
        raise ModelProviderError(f"all providers failed: {summary}")
