"""Builds real `ModelProvider` instances from `ModelProviderConfig`.

Scoped deliberately narrow: only `impl: anthropic` has a real adapter
(`aef.providers.anthropic_provider.AnthropicProvider`) today. A full
config-to-`Services` factory (memory/knowledge_graph/tools/policies) needs
a plugin-registry design this repo doesn't have yet — `MemoryConfig`
alone doesn't carry enough information to construct a real `mem0.Memory()`
(no embedder/vector-store/LLM choice in the schema), and there is no tool
registry mapping `tools.allow` name strings to `Tool` objects anywhere.
See docs/adr/0014 for why that's Phase 2 scope, not deferred-by-oversight.

This module exists because `impl: anthropic` specifically *is* fully
buildable today, and leaving it unbuilt was a real bug: `aef run` could
not run this repo's own `examples/hello_agent`, since nothing ever wired
a `model_provider` at all (see docs/adr/0014).
"""

from __future__ import annotations

from aef.config.schema import ModelProviderConfig
from aef.providers.base import FallbackProvider, ModelProvider

_SUPPORTED_IMPLS = ("anthropic",)


class UnsupportedProviderImplError(NotImplementedError):
    def __init__(self, impl: str) -> None:
        super().__init__(
            f"no ModelProvider adapter for impl={impl!r} yet; only "
            f"{_SUPPORTED_IMPLS!r} are implemented (see aef/providers/)"
        )


def _build_single(impl: str) -> ModelProvider:
    if impl == "anthropic":
        # Imported lazily: aef-core's `anthropic` extra is optional (constraint
        # #3's vendor isolation means only providers/ touches the SDK at all),
        # so importing aef.config itself must not require it — only actually
        # building an anthropic-backed provider should.
        from aef.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    raise UnsupportedProviderImplError(impl)


def build_model_provider(config: ModelProviderConfig) -> ModelProvider:
    """Builds the primary provider, and wraps it with `FallbackProvider` if
    `config.fallback` is non-empty. Every listed impl (primary and
    fallback) must be supported — an unbuildable fallback fails loudly at
    construction time rather than being silently dropped, matching this
    repo's established default-deny-on-ambiguity discipline (ADR 0010-0013)."""
    providers = [_build_single(config.impl)]
    providers.extend(_build_single(impl) for impl in config.fallback)
    if len(providers) == 1:
        return providers[0]
    return FallbackProvider(providers)
