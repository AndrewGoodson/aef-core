"""G4 — separation of powers.

The bulk of this gate is **structural** now, not inspected (04 §2.4): the
corpus, eval suite, gate code, and CI workflow are Zone B, so a diff reaching
them is already rejected by G0 and the gates themselves run from the base ref
regardless (ADR 0047). G4 does not re-litigate that.

What remains is the part no path check can see: **safety metadata inside
agent-authored code**. With self-coding, an agent writes `Node(...)` and
`Edge(...)` calls itself, and each of these declarations is load-bearing for
a control elsewhere in the kernel:

- `deterministic=True` on a node with side effects — `ReplayEngine`
  re-executes deterministic nodes, so the I/O repeats on every replay
  (ADR 0046).
- `idempotency_key_fn` returning a constant — defeats downstream
  deduplication entirely (ADR 0010).
- `fallback_node_id` — swallows errors *and* makes replay trust the record
  verbatim rather than verifying it (ADR 0036/0039).
- `requires_human_approval=False` — the HITL gate for that edge (ADR 0011).
- `requires_deterministic_fallback=False` — the emergent-routing marker.

None of these is forbidden outright — an agent may legitimately need a
fallback. What is forbidden is declaring them in the combination that
*disables a control while looking ordinary*, which is the shape a
reward-hacking change actually takes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult

# Mirrors 01-architecture.md §2.2 (expanded per 04 §1.9).
# The Edge-level controls only an owner may clear. Named once so the
# removal check and the literal-value check cannot drift apart.
OWNER_ONLY_EDGE_FLAGS: tuple[str, ...] = (
    "requires_human_approval",
    "requires_deterministic_fallback",
)

OWNER_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "deterministic",
        "side_effects",
        "idempotency_key_fn",
        "fallback_node_id",
        "requires_deterministic_fallback",
        "requires_human_approval",
    }
)

_NON_PURE = {"IO", "EXTERNAL_CALL", "MUTATING", "io", "external_call", "mutating"}


@dataclass(frozen=True)
class MetadataFinding:
    path: str
    line: int
    field: str
    problem: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.field}: {self.problem}"


def _kwargs(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}


def _literal(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _side_effect_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _resolve_aliases(tree: ast.Module) -> dict[str, str]:
    """Map local names back to `Node` / `Edge`.

    Matching the bare name was measured as evadable: `from aef.kernel import
    Edge as E` then `E(..., requires_human_approval=False)` produced zero
    findings, so an agent could disable a HITL gate by renaming the import
    (ADR 0064). Both alias forms are now resolved.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in ("Node", "Edge"):
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import aef.kernel as k` -> k.Node(...) resolves via attribute
                if alias.asname:
                    aliases.setdefault(f"__module__{alias.asname}", alias.name)
    return aliases


def _called_name(func: ast.expr, aliases: dict[str, str]) -> str | None:
    """The canonical `Node`/`Edge` a call refers to, through any alias."""
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id if func.id in ("Node", "Edge") else None)
    if isinstance(func, ast.Attribute) and func.attr in ("Node", "Edge"):
        # `aef.kernel.Node(...)` or `k.Node(...)`
        return func.attr
    return None


def scan_metadata(path: str, source: str) -> tuple[MetadataFinding, ...]:
    """Find safety-metadata declarations that disable a control."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        # G0 already reports the syntax error; not this gate's business.
        return ()

    findings: list[MetadataFinding] = []
    aliases = _resolve_aliases(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _called_name(node.func, aliases)
        if called is None:
            continue
        kwargs = _kwargs(node)

        if called == "Node":
            deterministic = _literal(kwargs["deterministic"]) if "deterministic" in kwargs else None
            side_effects = (
                _side_effect_name(kwargs["side_effects"]) if "side_effects" in kwargs else None
            )
            if deterministic is True and side_effects in _NON_PURE:
                findings.append(
                    MetadataFinding(
                        path=path,
                        line=node.lineno,
                        field="deterministic",
                        problem=(
                            f"deterministic=True with side_effects={side_effects} — ReplayEngine "
                            f"re-executes deterministic nodes, so the side effect repeats on "
                            f"every replay (ADR 0046)"
                        ),
                    )
                )
            if "fallback_node_id" in kwargs and _literal(kwargs["fallback_node_id"]) is not None:
                findings.append(
                    MetadataFinding(
                        path=path,
                        line=node.lineno,
                        field="fallback_node_id",
                        problem=(
                            "an agent-declared fallback swallows errors and makes replay trust "
                            "the record verbatim instead of verifying it (ADR 0036/0039) — "
                            "owner-only"
                        ),
                    )
                )
            key_fn = kwargs.get("idempotency_key_fn")
            if key_fn is not None and _is_constant_key_fn(key_fn):
                findings.append(
                    MetadataFinding(
                        path=path,
                        line=node.lineno,
                        field="idempotency_key_fn",
                        problem=(
                            "returns a constant, which collapses every call to one key and "
                            "defeats downstream deduplication (ADR 0010)"
                        ),
                    )
                )

        elif called == "Edge":
            for flag in OWNER_ONLY_EDGE_FLAGS:
                # Truthiness, not `is False`. Identity meant `0`, `[]` and `""`
                # all slipped through, and every one of them is
                # runtime-equivalent to the control being off — the executor
                # tests truthiness. Same evasion class ADR 0064 closed for
                # import aliases, left open on the value side (ADR 0079).
                if flag in kwargs and not _literal(kwargs[flag]):
                    findings.append(
                        MetadataFinding(
                            path=path,
                            line=node.lineno,
                            field=flag,
                            problem=(
                                f"{flag}={ast.unparse(kwargs[flag])} disables a control; "
                                f"only the owner may clear it"
                            ),
                        )
                    )

    return tuple(findings)


def _guarded_edges(source: str) -> dict[tuple[str, str], set[str]]:
    """`(from_node, to_node) -> {controls that are ON}` for every Edge.

    Used to compare the base ref against the candidate. Scanning only the
    candidate could never see a control that was **removed**: `flag in kwargs`
    is false when the kwarg is simply deleted, and the constructor default is
    off — so deleting the line was invisible while writing `=False` was a
    security event. Deleting it is the same act with better manners
    (ADR 0079).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    aliases = _resolve_aliases(tree)
    out: dict[tuple[str, str], set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _called_name(node.func, aliases) != "Edge":
            continue
        kwargs = _kwargs(node)
        if "from_node" not in kwargs or "to_node" not in kwargs:
            continue
        src = _literal(kwargs["from_node"])
        dst = _literal(kwargs["to_node"])
        if not isinstance(src, str) or not isinstance(dst, str):
            continue
        on = {
            flag
            for flag in OWNER_ONLY_EDGE_FLAGS
            if flag in kwargs and bool(_literal(kwargs[flag]))
        }
        if on:
            out[(src, dst)] = on
    return out


def scan_weakened_controls(
    path: str, base_source: str, head_source: str
) -> tuple[MetadataFinding, ...]:
    """Controls that were ON at the base ref and are not ON in the candidate."""
    base = _guarded_edges(base_source)
    head = _guarded_edges(head_source)
    findings: list[MetadataFinding] = []
    for edge, controls in sorted(base.items()):
        for flag in sorted(controls - head.get(edge, set())):
            findings.append(
                MetadataFinding(
                    path=path,
                    line=0,
                    field=flag,
                    problem=(
                        f"was {flag}=True on edge {edge[0]!r} -> {edge[1]!r} at the base ref "
                        f"and is not any more — removing a control is the same act as "
                        f"clearing it, and only the owner may do either"
                    ),
                )
            )
    return tuple(findings)


def _is_constant_key_fn(node: ast.expr) -> bool:
    """True for `lambda state: "literal"` — a key that never varies."""
    return isinstance(node, ast.Lambda) and isinstance(node.body, ast.Constant)


@dataclass(frozen=True)
class G4SeparationOfPowers(Gate):
    id: str = "G4"

    def run(self, ctx: GateContext) -> GateResult:
        findings: list[MetadataFinding] = []
        for entry in ctx.verdict.diff.entries:
            if entry.is_deletion or not entry.path.endswith(".py"):
                continue
            source = ctx.repo.show(ctx.head_ref, entry.path)
            findings.extend(scan_metadata(entry.path, source))
            # Base vs head, because a removed control leaves nothing in the
            # candidate to scan.
            base_source = (
                ctx.repo.show(ctx.base_ref, entry.path)
                if ctx.repo.path_exists_at(ctx.base_ref, entry.path)
                else ""
            )
            findings.extend(scan_weakened_controls(entry.path, base_source, source))

        if findings:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"{len(findings)} owner-only safety declaration(s) in agent-authored code — "
                    f"a change that disables a control while looking ordinary"
                ),
                evidence=tuple(str(f) for f in findings),
                security_event=True,
            )

        return GateResult(
            gate=self.id,
            outcome=GateOutcome.PASS,
            reason="no owner-only safety metadata declared by the candidate",
        )
