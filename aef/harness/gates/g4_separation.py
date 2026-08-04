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


def scan_metadata(path: str, source: str) -> tuple[MetadataFinding, ...]:
    """Find safety-metadata declarations that disable a control."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        # G0 already reports the syntax error; not this gate's business.
        return ()

    findings: list[MetadataFinding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        kwargs = _kwargs(node)

        if node.func.id == "Node":
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

        elif node.func.id == "Edge":
            for flag in ("requires_human_approval", "requires_deterministic_fallback"):
                if flag in kwargs and _literal(kwargs[flag]) is False:
                    findings.append(
                        MetadataFinding(
                            path=path,
                            line=node.lineno,
                            field=flag,
                            problem=(
                                f"{flag}=False disables a control; only the owner may clear it"
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
