"""The bounded catalogue a proposer may draw from.

Not code generation. A proposer applies NAMED operations, each of which is a
readable diff, individually revertible, and constrained by the memory record
that motivated it (ADR 0096).

The four properties every transformation must hold, each traceable to a
defect this program actually found:

1. The diff is human-readable and G0 sizes it.
2. The citation constrains the change — a proposal that cites a failure but
   would have made the same edit regardless is decoration.
3. One named operation, one coherent change.
4. **Nothing here may alter routing into a HITL-gated edge.** ADR 0089
   measured what that buys: a candidate that broke five scenarios and added
   `requires_human_approval=True` converted every regression into a G2 pass.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# Kwargs on `Edge` that a transformation may never introduce, remove or
# change. Enforced by `_touches_hitl_routing`, checked on the RESULT rather
# than trusted from the operation — a transformation that reasons about its
# own safety is the shape ADR 0080 found hackable.
HITL_KWARGS: frozenset[str] = frozenset(
    {"requires_human_approval", "requires_deterministic_fallback"}
)


class TransformationError(RuntimeError):
    """The transformation does not apply. Not an error in the candidate — a
    statement that this operation has nothing to offer here."""


@dataclass(frozen=True)
class Transformation:
    """One applied change, with the evidence that motivated it."""

    name: str
    target: str
    rationale: str
    source: str


def _node_constructions(tree: ast.AST) -> dict[str, ast.Call]:
    """`Node(id="x", ...)` calls, keyed by the declared id."""
    out: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = (
            callee.id
            if isinstance(callee, ast.Name)
            else callee.attr
            if isinstance(callee, ast.Attribute)
            else None
        )
        if name != "Node":
            continue
        for kw in node.keywords:
            if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    out[kw.value.value] = node
    return out


def _hitl_signature(source: str) -> list[tuple[str, str, str, object]]:
    """Every HITL-relevant kwarg on every Edge, as comparable tuples.

    Compared before and after so a transformation cannot change approval
    routing even by accident. Checked on the result, not asserted by the
    operation.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, str, str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = (
            callee.id
            if isinstance(callee, ast.Name)
            else callee.attr
            if isinstance(callee, ast.Attribute)
            else None
        )
        if name != "Edge":
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        src = kwargs.get("from_node")
        dst = kwargs.get("to_node")
        edge = (
            src.value if isinstance(src, ast.Constant) else "?",
            dst.value if isinstance(dst, ast.Constant) else "?",
        )
        for flag in sorted(HITL_KWARGS):
            if flag in kwargs:
                out.append((str(edge[0]), str(edge[1]), flag, ast.unparse(kwargs[flag])))
    return sorted(out)


def _assert_hitl_untouched(before: str, after: str) -> None:
    if _hitl_signature(before) != _hitl_signature(after):
        raise TransformationError(
            "transformation altered human-approval routing, which no transformation may do "
            "(ADR 0089: adding a HITL edge converts every regression into a G2 pass)"
        )


def add_deterministic_fallback(
    *, source: str, failing_node: str, handler: str, citation: str
) -> Transformation:
    """Give `failing_node` a `fallback_node_id` pointing at `handler`.

    The AEF-native structural answer to "this node raises": the executor
    already routes to `fallback_node_id` when a node raises, and replay
    already verifies that the recorded fallback still matches the declared
    one (ADR 0068). The diff is two tokens.

    The handler must ALREADY EXIST. Inventing one is code generation, and
    nothing in the gate set judges whether an invented handler is correct —
    only whether the corpus still passes, which an empty handler would also
    achieve (ADR 0096).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise TransformationError(f"source does not parse: {exc}") from exc

    constructions = _node_constructions(tree)
    if failing_node not in constructions:
        raise TransformationError(
            f"no Node(id={failing_node!r}) in this source; the memory names a node this "
            f"file does not declare"
        )
    if handler not in constructions:
        raise TransformationError(
            f"no Node(id={handler!r}) to fall back to. This transformation does not invent "
            f"a handler — an invented one would pass the gates by doing nothing"
        )
    if handler == failing_node:
        raise TransformationError(
            f"{failing_node!r} cannot fall back to itself; that is a loop, not a recovery"
        )

    call = constructions[failing_node]
    for kw in call.keywords:
        if kw.arg == "fallback_node_id":
            raise TransformationError(
                f"node {failing_node!r} already declares a fallback; changing an existing "
                f"one is a different operation with different evidence"
            )

    line = call.end_lineno
    col = call.end_col_offset
    if line is None or col is None:  # pragma: no cover - ast always sets these
        raise TransformationError("cannot locate the Node(...) call to edit")

    lines = source.splitlines(keepends=True)
    target = lines[line - 1]
    insert_at = col - 1  # just inside the closing paren
    if target[insert_at] != ")":
        raise TransformationError("Node(...) does not end where the parser said it does")
    separator = "" if target[:insert_at].rstrip().endswith(",") else ", "
    lines[line - 1] = (
        target[:insert_at] + f"{separator}fallback_node_id={handler!r}" + target[insert_at:]
    )
    rewritten = "".join(lines)

    try:
        ast.parse(rewritten)
    except SyntaxError as exc:  # pragma: no cover - guarded by the checks above
        raise TransformationError(f"transformation produced invalid Python: {exc}") from exc
    _assert_hitl_untouched(source, rewritten)

    return Transformation(
        name="add_deterministic_fallback",
        target=failing_node,
        rationale=(
            f"node {failing_node!r} raised in a recorded run ({citation}); routing its "
            f"failures to the existing {handler!r} handler instead of aborting the graph"
        ),
        source=rewritten,
    )
