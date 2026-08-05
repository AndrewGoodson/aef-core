"""Outcome classification — what G2 actually compares.

**This is not path identity, and the distinction is the whole milestone.**

The superseded design compared the candidate's execution *path* against the
recording and rejected any difference. Two reviewers found the same
consequence independently: since every non-trivial change alters the path,
that pipeline could only ever admit no-ops. It looked strict; it was
vacuous.

What G2 compares instead is the **outcome class**: did the run terminate,
did the plan reach the same status, were new errors introduced, was a policy
or HITL gate bypassed. A candidate is free to reach the same outcome by a
different route — that is what an improvement usually *is*.

Routing divergence is still computed and **reported**, because it is
genuinely informative to a human reading the report. It is never, on its
own, a rejection.

The asymmetry that makes this sound: only **previously-passing** scenarios
are held. A scenario the incumbent already failed may change freely — the
incumbent has no claim on behaviour it never got right.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aef.kernel.executor import NodeExecutionRecord
from aef.state import AEFState

# The key a node sets when a call was refused by policy. Explicit, because
# guessing from error TEXT was measured and is roughly ANTI-correlated: it
# missed 4 of 5 real refusals ("scope not granted", "HITL gate blocked",
# "guardrail rejected", a structured entry with no "error" key) and falsely
# flagged 3 of 3 innocuous ones ("connection denied by upstream DNS", "the
# policy document could not be parsed", "user denied the cookie banner").
# A signal that fires more often on the wrong input than the right one is
# worse than no signal, because it is acted on (ADR 0064).
POLICY_DENIED_KEY = "policy_denied"


@dataclass(frozen=True)
class Outcome:
    """The comparable summary of one scenario execution."""

    terminated: bool
    plan_status: str | None
    error_count: int
    policy_denials: int
    node_path: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """A scenario passed if it reached END with a completed plan and no
        errors. Deliberately strict: G2's job is to notice a regression, and
        a generous definition of "passed" would shrink the set of scenarios
        that hold the candidate to anything."""
        return self.terminated and self.plan_status == "done" and self.error_count == 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "terminated": self.terminated,
            "plan_status": self.plan_status,
            "error_count": self.error_count,
            "policy_denials": self.policy_denials,
            "node_path": list(self.node_path),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Outcome:
        return cls(
            terminated=bool(payload["terminated"]),
            plan_status=payload.get("plan_status"),
            error_count=int(payload["error_count"]),
            policy_denials=int(payload["policy_denials"]),
            node_path=tuple(payload.get("node_path", [])),
        )


def _is_policy_denial(entry: dict[str, Any]) -> bool:
    """Exact, not inferred. A node that was refused by `PolicyEngine` sets
    `policy_denied=True` on the error entry it appends; anything else is not
    counted. Under-counting an unmarked refusal is a known and bounded gap —
    mis-counting an unrelated timeout as one was neither."""
    return entry.get(POLICY_DENIED_KEY) is True


def classify(
    final_state: AEFState,
    trace: tuple[NodeExecutionRecord, ...] | None,
    *,
    terminated: bool,
) -> Outcome:
    return Outcome(
        terminated=terminated,
        plan_status=final_state.plan.status if final_state.plan is not None else None,
        error_count=len(final_state.errors),
        policy_denials=sum(1 for e in final_state.errors if _is_policy_denial(e)),
        node_path=tuple(r.node_id for r in (trace or ())),
    )


@dataclass(frozen=True)
class Comparison:
    scenario_id: str
    incumbent: Outcome
    candidate: Outcome

    @property
    def routing_diverged(self) -> bool:
        return self.incumbent.node_path != self.candidate.node_path

    @property
    def regressed(self) -> bool:
        """True only when a scenario the incumbent PASSED no longer passes,
        or the candidate newly trips a policy gate on it."""
        if not self.incumbent.passed:
            return False
        if not self.candidate.passed:
            return True
        return self.candidate.policy_denials > self.incumbent.policy_denials

    @property
    def summary(self) -> str:
        if self.regressed:
            return (
                f"{self.scenario_id}: REGRESSION — incumbent passed "
                f"(plan={self.incumbent.plan_status}, {self.incumbent.error_count} error(s)); "
                f"candidate did not (terminated={self.candidate.terminated}, "
                f"plan={self.candidate.plan_status}, {self.candidate.error_count} error(s), "
                f"{self.candidate.policy_denials} policy denial(s))"
            )
        if self.routing_diverged:
            # Reported, never rejected. See the module docstring.
            return (
                f"{self.scenario_id}: routing changed "
                f"{list(self.incumbent.node_path)} -> {list(self.candidate.node_path)} "
                f"(same outcome class; reported, not a rejection)"
            )
        return f"{self.scenario_id}: unchanged"
