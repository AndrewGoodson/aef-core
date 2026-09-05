"""Establish, with no live call, what a scenario scoring exactly 0.0000 with
zero cost tokens means — so floor repeat 3's `sum-13-cider-press: 0.0` can be
attributed instead of guessed at.

A stub provider that raises stands in for a transient harness failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a728ddfdde3c11ecd")

from aef.harness.corpus import load_corpus  # noqa: E402
from aef.harness.scenario_runner import load_graph, run_scenario  # noqa: E402
from aef.providers.base import (  # noqa: E402
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)


class Raising(ModelProvider):
    name = "raising"

    @property
    def default_model(self) -> str | None:
        return "stub"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ModelProviderError("claude exited 1: transient")


class Empty(ModelProvider):
    name = "empty"

    @property
    def default_model(self) -> str | None:
        return "stub"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="", model="stub", input_tokens=0, output_tokens=0)


corpus = load_corpus(Path(sys.argv[1]))
graph = load_graph("agents.summary.graph:build_graph")
scenario = next(s for s in corpus.scenarios if s.id == "sum-13-cider-press")

for label, provider in (("provider raises", Raising()), ("provider returns ''", Empty())):
    r = run_scenario(scenario, graph, None, cassette_miss="live", live_provider=provider)
    print(
        f"{label:22} score={r['score']:.4f} cost_tokens={r['cost_tokens']} "
        f"checks={r.get('checks', {}).get('passed', '-')}/"
        f"{r.get('checks', {}).get('total', '-')} failure={r.get('failure', '-')}"
    )
