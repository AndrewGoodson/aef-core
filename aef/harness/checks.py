"""Owner-declared task checks — the part of the score that can fail without
an error (ADR 0113).

Until these existed the corpus score was `task_completion`, and
`RuleBasedEvaluator` set that to 1.0 whenever the plan finished with no
errors. A graph that ran cleanly and wrote the wrong answer scored the same
as one that wrote the right one, so nothing the loop learned could move the
metric except "stop raising". autoresearch's whole method is one scalar
that can go down; this is that scalar's other half.

A check is **data, never code**. Scenarios are files a candidate can read,
and the gates re-execute them against candidate code; a check that could
execute would hand the candidate the judge. So a check is a dotted path
into the final state, one of four operators, and a value. That is enough
to say "the summary mentions X", "quality equals 1.0", "an answer exists",
and it is not enough to say anything a candidate could subvert by editing
the scenario it is scored on (scenarios are Zone C; ADR 0082).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aef.state import AEFState

OPS: frozenset[str] = frozenset({"equals", "contains", "regex", "exists"})


class CheckError(ValueError):
    """A malformed check. Raised at LOAD time, so a corpus with a typo in a
    check fails before any scenario runs rather than scoring everything 0."""


@dataclass(frozen=True)
class TaskCheck:
    path: str  # dotted path into AEFState, e.g. "scores.quality", "working_memory.answer"
    op: str
    value: Any = None

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise CheckError(f"check op {self.op!r} is not one of {sorted(OPS)}")
        if not self.path or self.path.startswith(".") or ".." in self.path:
            raise CheckError(f"check path {self.path!r} is not a dotted path")
        if self.op == "regex":
            if not isinstance(self.value, str):
                raise CheckError("regex check needs a string pattern")
            try:
                re.compile(self.value)
            except re.error as exc:
                raise CheckError(f"regex check pattern {self.value!r}: {exc}") from exc
        if self.op == "exists" and self.value is not None:
            raise CheckError("exists check takes no value")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": self.path, "op": self.op}
        if self.op != "exists":
            payload["value"] = self.value
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TaskCheck:
        try:
            return cls(path=str(payload["path"]), op=str(payload["op"]), value=payload.get("value"))
        except KeyError as exc:
            raise CheckError(f"check is missing {exc}") from exc


@dataclass(frozen=True)
class CheckReport:
    passed: int
    total: int
    failures: tuple[str, ...]  # one line per failed check, for the report

    @property
    def fraction(self) -> float:
        return 1.0 if self.total == 0 else self.passed / self.total


_MISSING = object()


def _resolve(state: AEFState, path: str) -> Any:
    """Walk a dotted path through the state's JSON form. List segments are
    integer indices. Returns `_MISSING` rather than raising so `exists` can
    be expressed and a failed lookup is a failed check, not a crash."""
    node: Any = state.model_dump(mode="json")
    for segment in path.split("."):
        if isinstance(node, dict):
            if segment not in node:
                return _MISSING
            node = node[segment]
        elif isinstance(node, list):
            try:
                node = node[int(segment)]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return node


def evaluate_checks(checks: Sequence[TaskCheck], final_state: AEFState) -> CheckReport:
    passed = 0
    failures: list[str] = []
    for check in checks:
        actual = _resolve(final_state, check.path)
        ok = _holds(check, actual)
        if ok:
            passed += 1
        else:
            shown = "<missing>" if actual is _MISSING else repr(actual)
            failures.append(f"{check.path} {check.op} {check.value!r}: got {shown}")
    return CheckReport(passed=passed, total=len(checks), failures=tuple(failures))


def _holds(check: TaskCheck, actual: Any) -> bool:
    if check.op == "exists":
        return actual is not _MISSING and actual is not None
    if actual is _MISSING:
        return False
    if check.op == "equals":
        return bool(actual == check.value)
    if check.op == "contains":
        if isinstance(actual, str):
            return str(check.value) in actual
        if isinstance(actual, list | dict):
            return check.value in actual
        return False
    if check.op == "regex":
        return isinstance(actual, str) and re.search(check.value, actual) is not None
    raise CheckError(f"unreachable op {check.op!r}")  # pragma: no cover - __post_init__ guards
