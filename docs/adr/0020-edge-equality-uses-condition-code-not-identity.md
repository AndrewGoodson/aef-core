# ADR 0020: `Edge` equality compares `condition` by `__code__`, not object identity — `Graph.diff()` was falsely reporting every rebuilt graph as changed

## Status
Accepted

## Context
Fresh logic read of `aef/kernel/graph.py` (per the build task's own §14
requirement — `diff(other)` is a mandatory subgraph API method meant to
support CI gating "before any subgraph promotion," per blueprint §2.4)
turned up a real bug in `Graph.diff()`'s edge comparison. `Edge` is a
frozen dataclass; its auto-generated `__eq__`/`__hash__` compare every
field, including `condition: RouteCondition` — a callable, most commonly
a lambda. Python function objects compare by identity, not by source
code. Reproduced directly: building the *same* graph twice (calling the
same `build_graph()`-style function twice, which is exactly what happens
on every CLI invocation, every test, every process restart) produces two
structurally-identical graphs whose `diff()` nonetheless reported every
edge with a non-default `condition` as **both** added and removed — a
phantom change with no real difference behind it.

This isn't a cosmetic annoyance: `diff()`'s entire stated purpose is
letting CI catch *real* structural changes before promoting a graph
version. If it also fires on every rebuild of an *unchanged* graph, it's
useless for that purpose — either every CI run shows spurious diffs (and
gets ignored), or worse, a genuinely broken diff check gets disabled
entirely because "it always shows changes."

## Decision
`Edge` now defines `__eq__`/`__hash__` explicitly (`@dataclass(frozen=True,
eq=False)`, since the auto-generated comparison is what needed replacing)
comparing `condition` by `getattr(condition, "__code__", condition)`
instead of the callable object itself. Confirmed directly (not assumed)
that this is the right primitive: two lambdas defined at the same source
location across separate calls produce equal — in CPython, frequently the
literal same — `__code__` objects, while two lambdas with genuinely
different bodies produce different ones. A callable without `__code__`
(e.g. a class instance implementing `__call__`) falls back to comparing
the callable itself, preserving today's identity-based behavior for that
case rather than guessing at a wrong heuristic.

Every other `Edge` field keeps ordinary value equality.

## Consequences
- `Graph.diff()` now correctly reports `is_empty` for a graph rebuilt from
  identical source, even when its edges have custom (non-default)
  conditions — verified both at the `Edge`-equality level and the
  `Graph.diff()` level, and confirmed a *genuinely* different condition
  (different lambda body) still shows up as a real diff.
- `Edge` instances remain hashable and usable in sets (`Graph.__post_init__`
  and `diff()` both rely on this), now with the corrected equality
  semantics backing that hashability.
- The `__code__`-based comparison is a heuristic, not a semantic-equality
  guarantee: two unrelated lambdas that happen to compile to identical
  bytecode (rare but possible for trivial bodies) would compare equal.
  Accepted — the same limitation already exists for anything comparing
  function behavior short of full symbolic execution, and the practical
  failure mode (marginally under-reporting a diff for a coincidentally
  identical-bytecode condition) is far less costly than the bug this
  fixes (over-reporting on every single rebuild).

## Alternatives Considered
- **Exclude `condition` from `Edge` equality entirely, treating routing
  behavior as out of scope for diffing.** Rejected: blueprint §2.4
  explicitly lists "edge conditions changed" as part of what structural
  diffing is for — dropping it from comparison entirely would silently
  miss a real category of graph change the diff is supposed to catch.
- **Compare by `condition.__qualname__` alone, without `__code__`.**
  Considered and rejected as strictly worse: two genuinely different
  lambdas defined at the same call site across different invocations
  (e.g. a factory function that sometimes builds `lambda s: True` and
  sometimes `lambda s: False` depending on a parameter) would share a
  `__qualname__` but have different `__code__` — comparing `__code__`
  catches this correctly; `__qualname__` alone would not.

## Confidence
High — the bug was concretely reproduced with a minimal repro before
writing any fix, the fix was verified to resolve exactly that repro while
still detecting a genuinely different condition, and the fallback for
non-function callables preserves prior behavior rather than guessing.
