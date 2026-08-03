"""Phase 2 interface stub: token optimization beyond provider-native prompt
caching (report §13). Provider prompt caching is each `ModelProvider`
adapter's own concern (stable prefixes, cached tool definitions) and isn't
modeled separately here; `TokenOptimizer` covers semantic caching,
structural compression, and per-node budget enforcement — none implemented
in Phase 0/1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CompressionResult:
    compressed_text: str
    original_tokens: int
    compressed_tokens: int


class TokenOptimizer(ABC):
    @abstractmethod
    def compress(self, text: str, *, token_budget: int) -> CompressionResult:
        """Report §13: never optimizes for fewer tokens as an end in itself
        — compress only enough to fit `token_budget` while preserving
        task-relevant information density."""
        raise NotImplementedError("TokenOptimizer is a Phase 2 interface; no backend is wired yet")
