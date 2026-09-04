"""Which error `build_run_config` reports first — pinned, not inherited.

ADR 0149's F7. `run_graph_module` used to build the model provider first and
call `build_domain_gates` second. Extracting `build_run_config` (ADR 0145)
put the validation first, so the same `aef.yaml` — one unbuildable provider,
one unresolvable evaluator suite — changed which error an adopter sees. Same
values, different first error, and nobody decided it.

REPRODUCED against a config with both faults:

    NEW first error: DomainGateError : evaluator suite 'nosuch.module:gate':
                     cannot import 'nosuch.module' (No module named 'nosuch')
    OLD first error: UnsupportedProviderImplError : no ModelProvider adapter
                     for impl='openai' yet

The new order is KEPT and pinned here: **validate before constructing.**
`build_domain_gates` resolves names and builds nothing; `build_model_provider`
constructs a live provider and, for `impl: anthropic`, imports a vendor SDK to
do it. The cheap, local, purely-declarative failure is the one worth reporting
first. The point of the test is not that this order is obviously right — it is
that it stops being whichever statement a refactor left on top.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aef.cli.run import build_run_config
from aef.config.domain_gates import DomainGateError
from aef.config.factory import UnsupportedProviderImplError

BOTH_FAULTS = """extends: _base
objectives: "x"
model_provider: {impl: claude_code, model: claude-opus-5, fallback: ["openai"]}
memory: {impl: in_memory}
tools: {allow: []}
policies: {require_hitl_above_risk: 0.5}
evaluator: {suites: ["nosuch.module:gate"]}
"""

PROVIDER_FAULT_ONLY = BOTH_FAULTS.replace('suites: ["nosuch.module:gate"]', "suites: []")


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "aef.yaml"
    path.write_text(text)
    return path


def test_build_run_config_reports_the_evaluator_before_the_provider(tmp_path: Path) -> None:
    with pytest.raises(DomainGateError) as exc:
        build_run_config(_config(tmp_path, BOTH_FAULTS))
    assert "nosuch.module" in str(exc.value)


def test_the_provider_error_still_arrives_when_the_evaluator_is_fine(tmp_path: Path) -> None:
    """The control: the reordering must not have made the provider error
    unreachable. A validation that swallows the second fault is worse than the
    ordering it fixed."""
    with pytest.raises(UnsupportedProviderImplError) as exc:
        build_run_config(_config(tmp_path, PROVIDER_FAULT_ONLY))
    assert "openai" in str(exc.value)


def test_no_config_path_builds_nothing_and_raises_nothing() -> None:
    """`None` means no `aef.yaml` was given: every field keeps its
    unconfigured default and neither builder runs."""
    config = build_run_config(None)
    assert config.model_provider is None
    assert config.policy_config is None
    assert config.context is None
    assert config.reflection == "rule_based"
    assert config.reflection_model is None
