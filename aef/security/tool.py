"""`Tool` interface, `PolicyEngine`, and audit logging (constraint #6).

Security default is deny: a tool with no declared scopes is denied, a scope
not in the allowlist is denied, and any call whose risk exceeds the
configured threshold requires explicit human-in-the-loop approval rather
than executing. This module assumes prompt injection will sometimes
succeed and is designed for containment (least-privilege scopes, explicit
HITL gates, a full audit trail), not detection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any]
    risk: float = 0.0  # 0..1 blast-radius estimate for this specific call


class Tool(ABC):
    name: str
    required_scopes: tuple[str, ...] = ()

    @abstractmethod
    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool. Callers MUST have obtained `PolicyDecision.ALLOW`
        (or explicit HITL approval) from a `PolicyEngine` first — this method
        does not itself enforce policy."""
        raise NotImplementedError


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HITL = "require_hitl"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is PolicyDecision.ALLOW


@dataclass(frozen=True)
class PolicyConfig:
    allowed_scopes: frozenset[str] = frozenset()
    forbidden_tool_names: frozenset[str] = frozenset()
    # Any call with risk > this threshold is routed to REQUIRE_HITL instead
    # of ALLOW, even if scopes check out. Default is effectively "never
    # auto-allow high risk": callers must configure this explicitly per
    # constraint #6 ("HITL approval above a configurable risk threshold").
    require_hitl_above_risk: float = 0.0


@dataclass(frozen=True)
class AuditEntry:
    tool: str
    call: ToolCall
    result: PolicyResult
    ts: datetime


class AuditLogWriter(ABC):
    @abstractmethod
    def write(self, entry: AuditEntry) -> None:
        raise NotImplementedError


class InMemoryAuditLogWriter(AuditLogWriter):
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class PolicyEngine:
    """Evaluates every tool call before execution. Deny-by-default: a tool
    must declare scopes, every declared scope must be explicitly allowlisted,
    and the call's risk must not exceed the configured HITL threshold."""

    def __init__(
        self,
        config: PolicyConfig | None = None,
        audit_log: AuditLogWriter | None = None,
        clock: Any = None,
    ) -> None:
        self._config = config or PolicyConfig()
        self._audit_log = audit_log or InMemoryAuditLogWriter()
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(self, tool: Tool, call: ToolCall) -> PolicyResult:
        result = self._decide(tool, call)
        self._audit_log.write(
            AuditEntry(tool=tool.name, call=call, result=result, ts=self._clock())
        )
        return result

    def _decide(self, tool: Tool, call: ToolCall) -> PolicyResult:
        if tool.name in self._config.forbidden_tool_names:
            return PolicyResult(PolicyDecision.DENY, f"tool {tool.name!r} is explicitly forbidden")
        if not tool.required_scopes:
            return PolicyResult(PolicyDecision.DENY, "tool declares no scopes; default-deny")
        missing = set(tool.required_scopes) - self._config.allowed_scopes
        if missing:
            return PolicyResult(PolicyDecision.DENY, f"missing scopes: {sorted(missing)}")
        if call.risk > self._config.require_hitl_above_risk:
            threshold = self._config.require_hitl_above_risk
            return PolicyResult(
                PolicyDecision.REQUIRE_HITL,
                f"risk {call.risk} exceeds require_hitl_above_risk={threshold}",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok")


__all__ = [
    "AuditEntry",
    "AuditLogWriter",
    "InMemoryAuditLogWriter",
    "PolicyConfig",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyResult",
    "Tool",
    "ToolCall",
]
