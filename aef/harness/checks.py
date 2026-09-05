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
into the final state, one of six operators, and a value. That is enough
to say "the summary mentions X", "quality equals 1.0", "an answer exists",
"the summary is at most 35 words", and it is not enough to say anything a
candidate could subvert by editing the scenario it is scored on (scenarios
are Zone C; ADR 0082).

**Data is not the same as safe.** `regex` is data, and a data-only pattern
still runs inside Python's backtracking engine. Every summary scenario in
`corpus/` declared its word cap as `^(?:\\s*\\S+){1,N}\\s*$`; a **match**
returns in 0.05 ms and a **failure** — one word over the cap — explores every
partition of the string and does not terminate. `re` has no timeout and this
repo takes no dependency for one, so the defence here is *static*: a pattern
whose repeated group can match one input many ways is refused, at scenario
load and again before every search (ADR 0166). The cap the corpus actually
wanted is `max_words`, which needs no regex at all.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aef.state import AEFState

OPS: frozenset[str] = frozenset({"equals", "contains", "regex", "exists", "max_words", "min_words"})
_WORD_COUNT_OPS: frozenset[str] = frozenset({"max_words", "min_words"})

# Above this, a pattern carrying ANY repeated group is refused rather than
# run. Truncating the input instead would change the predicate — "at most 35
# words" asked of the first 10,000 characters is a different question — so the
# backstop refuses loudly instead of answering a question nobody asked.
MAX_REGEX_INPUT_CHARS = 10_000


class CheckError(ValueError):
    """A malformed check. Raised at LOAD time, so a corpus with a typo in a
    check fails before any scenario runs rather than scoring everything 0."""


class CatastrophicPatternError(CheckError):
    """A `regex` check whose pattern can backtrack exponentially.

    Its own type because this is not a typo: the pattern compiles, matches
    correctly, and passes every test whose input happens to match. It fails
    only on a NON-match, and then it fails by never returning — which reads
    as a slow model, not as a broken check (ADR 0156 §D2, ADR 0166).
    """


# --- the static ReDoS detector (ADR 0166) ---------------------------------
#
# Deliberately small, and deliberately conservative. It is not a decision
# procedure for regular-expression ambiguity — that needs an automaton — it is
# a rule that catches the two families this corpus and the literature actually
# produce, and refuses a few safe patterns along the way:
#
#   1. a repeated group whose body contains a NULLABLE quantifier
#      (`*`, `?`, `{0,m}`) — `(?:\s*\S+){1,35}`, the corpus's word cap. The
#      nullable separator lets two adjacent iterations split one token, so the
#      number of ways to match grows exponentially in the input length.
#   2. a repeated group whose body is a SINGLE unbounded-quantified atom —
#      `(a+)+`, `(a*)*`, `(a+)*`, the textbook case. Same cause: nothing
#      forces a boundary between one iteration and the next.
#
# `(?:\s+\S+){0,34}` is allowed, and must be: `\s+` is not nullable, so every
# iteration boundary is forced and the match is linear. That is the rewrite
# the error message offers.
#
# False positives are the intended direction of error. A refused-but-safe
# pattern is a loud message with a stated rewrite; a missed unsafe one hangs
# the scorer forever and looks like a slow model.


def _skip_class(pattern: str, i: int) -> int:
    """Index just past the character class starting at `pattern[i] == '['`."""
    i += 1
    if i < len(pattern) and pattern[i] == "^":
        i += 1
    if i < len(pattern) and pattern[i] == "]":  # a literal ']' first in the class
        i += 1
    while i < len(pattern) and pattern[i] != "]":
        i += 2 if pattern[i] == "\\" else 1
    return i + 1


def _quantifier_at(pattern: str, i: int) -> tuple[str, int]:
    """The repetition quantifier at `i`, and the index after it.

    `("", i)` when there is none. A trailing `?`/`+` (lazy/possessive) is
    consumed as part of the quantifier rather than read as a second one, so
    `\\S+?` is one unbounded quantifier and not an unbounded plus a nullable.
    """
    if i >= len(pattern):
        return "", i
    ch = pattern[i]
    if ch in "*+?":
        j = i + 1
    elif ch == "{":
        close = pattern.find("}", i)
        if close == -1:
            return "", i
        inner = pattern[i + 1 : close]
        if inner in ("", ",") or re.fullmatch(r"\d*(?:,\d*)?", inner) is None:
            return "", i  # a literal brace, not a repetition
        j = close + 1
    else:
        return "", i
    if j < len(pattern) and pattern[j] in "?+":
        j += 1
    return pattern[i:j], j


def _quantifier_core(quantifier: str) -> str:
    """`{1,3}?` -> `{1,3}`, `+?` -> `+`. The laziness marker changes which
    match is found first, never how many there are to try."""
    if len(quantifier) > 1 and quantifier[-1] in "?+":
        return quantifier[:-1]
    return quantifier


def _is_nullable(quantifier: str) -> bool:
    core = _quantifier_core(quantifier)
    if core in ("*", "?"):
        return True
    if core.startswith("{"):
        low = core[1:-1].split(",")[0]
        return low == "" or int(low) == 0
    return False


def _is_unbounded(quantifier: str) -> bool:
    core = _quantifier_core(quantifier)
    if core in ("*", "+"):
        return True
    if core.startswith("{"):
        inner = core[1:-1]
        return "," in inner and inner.split(",")[1] == ""
    return False


def _atoms(source: str) -> list[tuple[str, str]]:
    """`(atom, quantifier)` pairs at the TOP level of `source`.

    A group is one atom; its contents are not descended into here, because
    `_repeated_group_bodies` walks every group in the whole pattern anyway.
    """
    out: list[tuple[str, str]] = []
    i, n = 0, len(source)
    while i < n:
        start = i
        ch = source[i]
        if ch == "\\":
            i += 2
        elif ch == "[":
            i = _skip_class(source, i)
        elif ch == "(":
            depth, i = 1, i + 1
            while i < n and depth:
                if source[i] == "\\":
                    i += 2
                elif source[i] == "[":
                    i = _skip_class(source, i)
                else:
                    if source[i] == "(":
                        depth += 1
                    elif source[i] == ")":
                        depth -= 1
                    i += 1
        else:
            i += 1
        atom = source[start:i]
        quantifier, i = _quantifier_at(source, i)
        out.append((atom, quantifier))
    return out


_GROUP_PREFIXES = ("?<=", "?<!", "?P=", "?:", "?=", "?!", "?>")


def _group_body(raw: str) -> str:
    """What sits between the parentheses, minus the `(?:` / `(?P<x>` / lookaround
    marker, so `?:\\s*\\S+` becomes `\\s*\\S+`."""
    if not raw.startswith("?"):
        return raw
    if raw.startswith("?P<"):
        close = raw.find(">")
        return raw[close + 1 :] if close != -1 else raw
    for prefix in _GROUP_PREFIXES:
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def _repeated_group_bodies(pattern: str) -> list[str]:
    """Every group in `pattern` that carries a repetition quantifier, as its
    body. Escapes and character classes are skipped, so `\\(` and `[()]` are
    not mistaken for grouping."""
    bodies: list[str] = []
    stack: list[int] = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            i += 2
        elif ch == "[":
            i = _skip_class(pattern, i)
        elif ch == "(":
            stack.append(i)
            i += 1
        elif ch == ")":
            if stack:
                start = stack.pop()
                quantifier, _ = _quantifier_at(pattern, i + 1)
                if quantifier:
                    bodies.append(_group_body(pattern[start + 1 : i]))
            i += 1
        else:
            i += 1
    return bodies


def _rewrite_hint(pattern: str, body: str, why: str) -> str:
    return (
        f"regex check pattern {pattern!r} can backtrack exponentially: the repeated group "
        f"({body}) {why}, so one input can be matched many ways and a NON-match explores all "
        f"of them. Python's `re` has no timeout, so this is refused rather than run. "
        f"For a word cap use the op that needs no regex — "
        f'{{"op": "max_words", "value": N}} (with {{"op": "min_words", "value": 1}} if the '
        f"text must be non-empty) — instead of ^(?:\\s*\\S+){{1,N}}\\s*$. If you need a "
        f"regex, make every separator non-nullable: ^\\s*\\S+(?:\\s+\\S+){{0,N-1}}\\s*$."
    )


def refuse_catastrophic_regex(pattern: str) -> None:
    """Raise `CatastrophicPatternError` if `pattern` has a repeated group that
    can match one input many ways. Silent otherwise."""
    for body in _repeated_group_bodies(pattern):
        atoms = _atoms(body)
        nullable = [atom for atom, quantifier in atoms if _is_nullable(quantifier)]
        if nullable:
            raise CatastrophicPatternError(
                _rewrite_hint(
                    pattern,
                    body,
                    f"repeats a body containing the nullable quantifier {nullable[0]!r} "
                    f"(it can match the empty string, so iteration boundaries are not forced)",
                )
            )
        if len(atoms) == 1 and _is_unbounded(atoms[0][1]):
            raise CatastrophicPatternError(
                _rewrite_hint(
                    pattern,
                    body,
                    "repeats a body that is itself one unbounded quantifier — the "
                    "(x+)+ shape, where nothing separates one iteration from the next",
                )
            )


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
            # At LOAD time, so a corpus carrying the old word cap is refused
            # before any scenario runs rather than hanging one of them.
            refuse_catastrophic_regex(self.value)
        if self.op in _WORD_COUNT_OPS:
            # `bool` is an `int`; a check reading `{"op": "max_words", "value":
            # true}` is a mistake, not a cap of one.
            if isinstance(self.value, bool) or not isinstance(self.value, int):
                raise CheckError(f"{self.op} check needs an integer word count")
            if self.value < 0:
                raise CheckError(f"{self.op} check needs a non-negative word count")
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
    if check.op in _WORD_COUNT_OPS:
        # Whitespace-separated tokens, which is what "35 words" meant when the
        # corpus expressed it as a regex. A non-string fails rather than being
        # stringified: `len(str([1, 2]).split())` is 2, and a check that
        # silently passes on the wrong kind of value is worse than one that
        # fails loudly on it.
        if not isinstance(actual, str):
            return False
        words = len(actual.split())
        return words <= int(check.value) if check.op == "max_words" else words >= int(check.value)
    if check.op == "regex":
        if not isinstance(actual, str):
            return False
        pattern = str(check.value)
        # Defence in depth. `__post_init__` already refused this at load, but
        # `_holds` is the only place a pattern actually meets an input, and a
        # `TaskCheck` can reach here from an unvalidated construction.
        refuse_catastrophic_regex(pattern)
        if len(actual) > MAX_REGEX_INPUT_CHARS and _repeated_group_bodies(pattern):
            raise CatastrophicPatternError(
                f"refusing to run regex check {pattern!r} against {len(actual)} characters: "
                f"the pattern repeats a group and the input is over "
                f"{MAX_REGEX_INPUT_CHARS} characters. The static detector above is "
                f"conservative, not a proof, and truncating the input would answer a "
                f"different question than the check asked. Narrow the path, or use "
                f"max_words/min_words/contains."
            )
        return re.search(pattern, actual) is not None
    raise CheckError(f"unreachable op {check.op!r}")  # pragma: no cover - __post_init__ guards
