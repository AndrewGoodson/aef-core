from typing import Any

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
