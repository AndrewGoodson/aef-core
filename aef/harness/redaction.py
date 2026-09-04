"""Redaction at the harvest boundary (ADR 0119).

`harvest` promotes real runs into the corpus, and the corpus lives in git.
A real run's objective, working memory and tool results carry whatever the
tenant typed: addresses, tokens, account numbers. Without a redaction step,
"learn from live runs" means "commit tenant data", and the trust case's
criterion about real tenants cannot be met by a system that leaks them.

Three rules.

**Redact the INPUT, then re-execute; never patch the recorded trace.** A
trace redacted in place is a run that never happened — the agent saw the
real values. Harvest already refuses a run that does not re-execute
identically; redaction reuses that: the redacted initial state is re-run,
and the run is admitted only if it still fails the same way. A graph whose
behaviour depended on the secret (it branched on the token) changes
behaviour under redaction and is REJECTED, not recorded. The scenario the
corpus keeps is then honestly "given this redacted input, this happened".

**Scan the output before writing.** After re-execution, the scenario that
would be saved is scanned with the same patterns. A match means the graph
reintroduced a secret from somewhere the input redaction could not reach
(a tool, an environment), and the run is rejected. This is the planted-fault
check on the redactor itself, run every time rather than once at authoring.

**Patterns are data, and conservative by default.** Emails, bearer/API
tokens, and long opaque strings. False positives cost a scenario; false
negatives cost a tenant. Owners extend the list; nothing here shortens it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from aef.state import AEFState

# Order matters only for the label a match gets; a string matching two
# patterns is redacted by the first.
DEFAULT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("api_key", r"\b(?:sk|pk|rk|ak)[-_](?:live|test|ant|proj)?[-_]?[A-Za-z0-9]{16,}\b"),
    ("bearer", r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    ("aws_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("opaque_secret", r"\b[A-Za-z0-9+/=_-]{40,}\b"),
)


class RedactionError(ValueError):
    pass


@dataclass(frozen=True)
class RedactionPolicy:
    patterns: tuple[tuple[str, str], ...] = DEFAULT_PATTERNS
    # Keys dropped from `working_memory` outright, whatever they hold.
    drop_working_memory_keys: tuple[str, ...] = ("api_key", "token", "secret", "password")
    _compiled: tuple[tuple[str, re.Pattern[str]], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        compiled = []
        for label, pattern in self.patterns:
            try:
                compiled.append((label, re.compile(pattern)))
            except re.error as exc:
                raise RedactionError(
                    f"redaction pattern {label!r} does not compile: {exc}"
                ) from exc
        object.__setattr__(self, "_compiled", tuple(compiled))

    def redact_text(self, text: str) -> tuple[str, int]:
        count = 0
        for label, pattern in self._compiled:
            text, n = pattern.subn(f"[REDACTED:{label}]", text)
            count += n
        return text, count

    def redact_value(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            out: dict[Any, Any] = {}
            total = 0
            for k, v in value.items():
                v2, n = self.redact_value(v)
                out[k] = v2
                total += n
            return out, total
        if isinstance(value, list):
            items = [self.redact_value(v) for v in value]
            return [v for v, _ in items], sum(n for _, n in items)
        return value, 0

    def redact_state(self, state: AEFState) -> tuple[AEFState, int]:
        """A redacted copy of the state and the number of substitutions,
        including dropped working-memory keys."""
        payload = state.model_dump(mode="json")
        dropped = 0
        wm = payload.get("working_memory") or {}
        for key in list(wm):
            if key in self.drop_working_memory_keys:
                del wm[key]
                dropped += 1
        redacted, count = self.redact_value(payload)
        return AEFState.model_validate(redacted), count + dropped

    def find(self, value: Any) -> tuple[str, ...]:
        """Labels of every pattern that still matches anywhere in `value`.
        Empty means clean. This is the output scan."""
        text = _flatten(value)
        return tuple(label for label, pattern in self._compiled if pattern.search(text))


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(f"{k}\n{_flatten(v)}" for k, v in value.items())
    if isinstance(value, list | tuple):
        return "\n".join(_flatten(v) for v in value)
    return str(value)
