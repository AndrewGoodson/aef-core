import math
from typing import Any

import pytest

from aef.security.tool import (
    InMemoryAuditLogWriter,
    PolicyConfig,
    PolicyDecision,
    PolicyEngine,
    Tool,
    ToolCall,
)


class _StubTool(Tool):
    def __init__(self, name: str, required_scopes: tuple[str, ...] = ()) -> None:
        self.name = name
        self.required_scopes = required_scopes

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


def test_tool_with_no_declared_scopes_is_denied_by_default() -> None:
    engine = PolicyEngine()
    result = engine.evaluate(_StubTool("mystery"), ToolCall(tool_name="mystery", arguments={}))
    assert result.decision is PolicyDecision.DENY
    assert not result.allowed


def test_scope_not_in_allowlist_is_denied() -> None:
    config = PolicyConfig(allowed_scopes=frozenset({"az_cli_ro"}))
    engine = PolicyEngine(config)
    tool = _StubTool("delete_resource", required_scopes=("resource_delete",))
    result = engine.evaluate(tool, ToolCall(tool_name="delete_resource", arguments={}))
    assert result.decision is PolicyDecision.DENY
    assert "resource_delete" in result.reason


def test_explicitly_forbidden_tool_denied_even_with_allowed_scope() -> None:
    config = PolicyConfig(
        allowed_scopes=frozenset({"resource_delete"}),
        forbidden_tool_names=frozenset({"delete_resource"}),
    )
    engine = PolicyEngine(config)
    tool = _StubTool("delete_resource", required_scopes=("resource_delete",))
    result = engine.evaluate(tool, ToolCall(tool_name="delete_resource", arguments={}))
    assert result.decision is PolicyDecision.DENY


def test_allowed_scope_and_low_risk_is_allowed() -> None:
    config = PolicyConfig(allowed_scopes=frozenset({"az_cli_ro"}), require_hitl_above_risk=0.7)
    engine = PolicyEngine(config)
    tool = _StubTool("az_query", required_scopes=("az_cli_ro",))
    result = engine.evaluate(tool, ToolCall(tool_name="az_query", arguments={}, risk=0.1))
    assert result.decision is PolicyDecision.ALLOW
    assert result.allowed


def test_risk_above_threshold_requires_hitl_not_deny() -> None:
    config = PolicyConfig(allowed_scopes=frozenset({"az_cli_ro"}), require_hitl_above_risk=0.7)
    engine = PolicyEngine(config)
    tool = _StubTool("az_query", required_scopes=("az_cli_ro",))
    result = engine.evaluate(tool, ToolCall(tool_name="az_query", arguments={}, risk=0.9))
    assert result.decision is PolicyDecision.REQUIRE_HITL
    assert not result.allowed


def test_default_hitl_threshold_is_zero_so_any_positive_risk_requires_approval() -> None:
    config = PolicyConfig(allowed_scopes=frozenset({"az_cli_ro"}))
    engine = PolicyEngine(config)
    tool = _StubTool("az_query", required_scopes=("az_cli_ro",))
    result = engine.evaluate(tool, ToolCall(tool_name="az_query", arguments={}, risk=0.01))
    assert result.decision is PolicyDecision.REQUIRE_HITL


def test_every_evaluation_is_audit_logged() -> None:
    audit_log = InMemoryAuditLogWriter()
    engine = PolicyEngine(audit_log=audit_log)
    tool = _StubTool("mystery")
    engine.evaluate(tool, ToolCall(tool_name="mystery", arguments={"x": 1}))
    assert len(audit_log.entries) == 1
    entry = audit_log.entries[0]
    assert entry.tool == "mystery"
    assert entry.call.arguments == {"x": 1}
    assert entry.result.decision is PolicyDecision.DENY
    assert entry.ts is not None


def test_audit_log_accumulates_across_multiple_calls() -> None:
    audit_log = InMemoryAuditLogWriter()
    engine = PolicyEngine(audit_log=audit_log)
    tool = _StubTool("mystery")
    for _ in range(3):
        engine.evaluate(tool, ToolCall(tool_name="mystery", arguments={}))
    assert len(audit_log.entries) == 3


def test_tool_name_mismatch_denied_even_with_valid_scope() -> None:
    """A ToolCall whose declared tool_name doesn't match the Tool object
    actually being evaluated must be denied outright — this is the case a
    lookup bug or successful prompt injection could produce: policy gets
    evaluated against the right scopes for the wrong tool."""
    config = PolicyConfig(allowed_scopes=frozenset({"az_cli_ro"}))
    engine = PolicyEngine(config)
    tool = _StubTool("az_query", required_scopes=("az_cli_ro",))
    mismatched_call = ToolCall(tool_name="totally_different_tool", arguments={})

    result = engine.evaluate(tool, mismatched_call)

    assert result.decision is PolicyDecision.DENY
    assert "mismatch" in result.reason
    assert "totally_different_tool" in result.reason
    assert "az_query" in result.reason


def test_tool_name_mismatch_checked_before_forbidden_and_scope_checks() -> None:
    """Mismatch must be caught first — a call claiming to be some other,
    innocuous-sounding tool name should not slip past the forbidden-name
    check just because that check keys off tool.name, not call.tool_name."""
    config = PolicyConfig(
        allowed_scopes=frozenset({"resource_delete"}),
        forbidden_tool_names=frozenset({"delete_resource"}),
    )
    engine = PolicyEngine(config)
    tool = _StubTool("delete_resource", required_scopes=("resource_delete",))
    mismatched_call = ToolCall(tool_name="harmless_sounding_name", arguments={})

    result = engine.evaluate(tool, mismatched_call)

    assert result.decision is PolicyDecision.DENY
    assert "mismatch" in result.reason


def test_tool_name_mismatch_is_audit_logged() -> None:
    audit_log = InMemoryAuditLogWriter()
    engine = PolicyEngine(audit_log=audit_log)
    tool = _StubTool("real_tool", required_scopes=("x",))
    engine.evaluate(tool, ToolCall(tool_name="spoofed_name", arguments={}))

    assert len(audit_log.entries) == 1
    assert audit_log.entries[0].result.decision is PolicyDecision.DENY
    assert audit_log.entries[0].tool == "real_tool"


def test_toolcall_rejects_nan_risk() -> None:
    """Reproduces a real, confirmed HITL-gate bypass: `call.risk >
    threshold` is False for any threshold when risk is NaN (NaN compares
    False against everything in Python), so a NaN risk silently ALLOWed
    instead of REQUIRE_HITL, defeating the module's own default-deny
    design. See docs/adr/0025."""
    with pytest.raises(ValueError, match="finite"):
        ToolCall(tool_name="x", arguments={}, risk=math.nan)


def test_toolcall_rejects_infinite_risk() -> None:
    with pytest.raises(ValueError, match="finite"):
        ToolCall(tool_name="x", arguments={}, risk=math.inf)


def test_toolcall_rejects_risk_outside_zero_to_one() -> None:
    with pytest.raises(ValueError, match="0..1"):
        ToolCall(tool_name="x", arguments={}, risk=1.5)
    with pytest.raises(ValueError, match="0..1"):
        ToolCall(tool_name="x", arguments={}, risk=-0.1)


def test_policyconfig_rejects_nan_hitl_threshold() -> None:
    """Same bypass, from the other side of the `>` comparison: a NaN
    require_hitl_above_risk threshold would silently disable the HITL gate
    for every call regardless of risk."""
    with pytest.raises(ValueError, match="finite"):
        PolicyConfig(require_hitl_above_risk=math.nan)


def test_policyconfig_rejects_threshold_at_or_above_one() -> None:
    """Reproduces the residual half of the 0025 asymmetry (see docs/adr/0035):
    ToolCall.risk is bounded 0..1, so a require_hitl_above_risk threshold of
    1.0 (or higher) makes `call.risk > threshold` unreachable — the single
    most dangerous call (risk exactly 1.0) auto-ALLOWs instead of routing to
    REQUIRE_HITL. The threshold must stay strictly below 1.0 so the gate is
    always reachable."""
    with pytest.raises(ValueError, match="0.0.*1.0"):
        PolicyConfig(require_hitl_above_risk=1.0)
    with pytest.raises(ValueError, match="0.0.*1.0"):
        PolicyConfig(require_hitl_above_risk=1.5)
    with pytest.raises(ValueError, match="0.0.*1.0"):
        PolicyConfig(require_hitl_above_risk=-0.1)


def test_max_risk_call_routes_to_hitl_not_allow_at_the_highest_valid_threshold() -> None:
    """The highest valid threshold (just below 1.0) must still gate a
    max-risk call — proving the bound closes the bypass end to end."""
    config = PolicyConfig(allowed_scopes=frozenset({"net"}), require_hitl_above_risk=0.999)
    engine = PolicyEngine(config)
    tool = _StubTool("t", required_scopes=("net",))
    result = engine.evaluate(tool, ToolCall(tool_name="t", arguments={}, risk=1.0))
    assert result.decision is PolicyDecision.REQUIRE_HITL
