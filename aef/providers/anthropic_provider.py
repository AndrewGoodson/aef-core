"""Anthropic adapter for `ModelProvider`. This module (and no other outside
`providers/`/`services/*/adapters/`) is allowed to import the `anthropic`
SDK directly (constraint #3).
"""

from __future__ import annotations

from typing import Any, Protocol, cast

import anthropic

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)


class _AnthropicClient(Protocol):
    """The slice of `anthropic.Anthropic` this adapter actually calls —
    lets tests inject a fake client without touching the network."""

    messages: Any


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, client: _AnthropicClient | None = None) -> None:
        self._client: _AnthropicClient = client or cast(
            _AnthropicClient, anthropic.Anthropic(api_key=api_key)
        )

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system = "\n".join(m.content for m in request.messages if m.role == "system") or None
        messages = [
            {"role": m.role, "content": m.content} for m in request.messages if m.role != "system"
        ]
        # CompletionRequest.metadata is vendor-neutral (arbitrary str keys);
        # Anthropic's own API only accepts a single "user_id" key under
        # `metadata` (for their abuse-detection tracking). Pass it through
        # when present rather than silently dropping it — every other
        # metadata key is meaningless to this specific vendor and is
        # correctly ignored here, not a place a translation layer can do
        # anything about it.
        user_id = request.metadata.get("user_id")
        anthropic_metadata = {"user_id": user_id} if user_id is not None else None
        try:
            response = self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=system,
                messages=messages,
                metadata=anthropic_metadata,
            )
        except anthropic.APIError as exc:
            raise ModelProviderError(f"anthropic API error: {exc}") from exc

        content = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        return CompletionResult(
            content=content,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
        )
