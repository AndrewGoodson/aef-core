"""G0 — zone, size, and static safety. The cheapest gate, run first.

Rejects, in order of cost:

1. **Zone / mode violations** (from `candidate.py`): anything outside Zone A,
   any symlink, submodule, or executable bit.
2. **Diff size over budget.** A change too large to be meaningfully verified
   is auto-rejected rather than surfaced — Q-A1, owner default: 200 changed
   lines and 3 files. Restrictive on purpose; loosen only with evidence.
3. **Static safety of the Python that would land**, by AST.

The import rule is an **allowlist, not a denylist** (constraint #6's
deny-by-default, applied to code rather than tools). A denylist has to
anticipate every escape — `subprocess`, `ctypes`, `importlib`, `socket`,
`pickle`, and whatever ships next release. An allowlist only has to describe
what an agent legitimately needs, and anything novel is denied by having
been left out rather than by having been foreseen.

Vendor isolation (constraint #3) falls out of the same rule: `anthropic`,
`openai`, `mem0`, and `neo4j` are not on the allowlist, so agent-authored
code cannot import them regardless of where it sits.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult

# Deny-by-default: what agent-authored code may import. `aef` is the point —
# an agent composes the framework; it does not reach around it.
DEFAULT_IMPORT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "aef",
        "__future__",
        "abc",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "itertools",
        "json",
        "math",
        "operator",
        "re",
        "statistics",
        "string",
        "textwrap",
        "typing",
        "uuid",
    }
)

# Names that grant arbitrary execution or reflection regardless of imports.
FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {"eval", "exec", "compile", "__import__", "breakpoint", "memoryview"}
)

# Attribute access that reaches the interpreter's own machinery. `__globals__`
# on any function reaches its module namespace, which is a general escape.
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {"__globals__", "__builtins__", "__subclasses__", "__bases__", "__mro__", "__code__"}
)

DEFAULT_MAX_CHANGED_LINES = 200
DEFAULT_MAX_CHANGED_FILES = 3


@dataclass(frozen=True)
class StaticFinding:
    path: str
    line: int
    problem: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.problem}"


@dataclass(frozen=True)
class G0StaticSafety(Gate):
    id: str = "G0"
    import_allowlist: frozenset[str] = field(default_factory=lambda: DEFAULT_IMPORT_ALLOWLIST)
    max_changed_lines: int = DEFAULT_MAX_CHANGED_LINES
    max_changed_files: int = DEFAULT_MAX_CHANGED_FILES

    def run(self, ctx: GateContext) -> GateResult:
        verdict = ctx.verdict

        if not verdict.allowed:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason="candidate touches paths outside Zone A, or lands a non-regular file",
                evidence=verdict.reasons,
                security_event=bool(verdict.security_events),
            )

        size_failure = self._check_size(ctx)
        if size_failure is not None:
            return size_failure

        findings = self._scan(ctx)
        if findings:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=f"{len(findings)} static-safety violation(s) in agent-authored code",
                evidence=tuple(str(f) for f in findings),
            )

        return GateResult(
            gate=self.id,
            outcome=GateOutcome.PASS,
            reason=(
                f"{verdict.diff.changed_files} file(s), {verdict.diff.changed_lines} line(s), "
                f"all Zone A, no static-safety violations"
            ),
        )

    def _check_size(self, ctx: GateContext) -> GateResult | None:
        diff = ctx.verdict.diff
        max_lines = ctx.limits.get("max_changed_lines", self.max_changed_lines)
        max_files = ctx.limits.get("max_changed_files", self.max_changed_files)

        unmeasurable = diff.unmeasurable
        if unmeasurable:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    "git will not compute a change size for one or more files, so the "
                    "size budget cannot be applied — an unmeasurable change is rejected, "
                    "not counted as zero"
                ),
                evidence=tuple(
                    f"{p}: size not computable (binary or marked binary)" for p in unmeasurable
                ),
            )

        over: list[str] = []
        if diff.changed_lines > max_lines:
            over.append(f"{diff.changed_lines} changed lines exceeds the budget of {max_lines}")
        if diff.changed_files > max_files:
            over.append(f"{diff.changed_files} changed files exceeds the budget of {max_files}")
        if not over:
            return None
        return GateResult(
            gate=self.id,
            outcome=GateOutcome.FAIL,
            reason=(
                "diff exceeds the size budget — a change too large to be meaningfully "
                "verified is rejected, not surfaced (Q-A1)"
            ),
            evidence=tuple(over),
        )

    def _scan(self, ctx: GateContext) -> tuple[StaticFinding, ...]:
        findings: list[StaticFinding] = []
        for entry in ctx.verdict.diff.entries:
            if entry.is_deletion or not entry.path.endswith(".py"):
                continue
            # Read from the HEAD ref, not the working tree: the working tree
            # may hold uncommitted edits that are not part of the candidate.
            source = ctx.repo.show(ctx.head_ref, entry.path)
            findings.extend(scan_source(entry.path, source, self.import_allowlist))
        return tuple(findings)


def _root_module(name: str) -> str:
    return name.split(".", 1)[0]


def scan_source(
    path: str, source: str, allowlist: frozenset[str] = DEFAULT_IMPORT_ALLOWLIST
) -> tuple[StaticFinding, ...]:
    """AST-scan one agent-authored module. Never executes it."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return (StaticFinding(path=path, line=exc.lineno or 0, problem=f"syntax error: {exc.msg}"),)

    findings: list[StaticFinding] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_module(alias.name)
                if root not in allowlist:
                    findings.append(
                        StaticFinding(
                            path=path,
                            line=node.lineno,
                            problem=(
                                f"import of {alias.name!r} is not on the allowlist "
                                f"(agent-authored code may import: {', '.join(sorted(allowlist))})"
                            ),
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside Zone A
                continue
            root = _root_module(node.module or "")
            if root not in allowlist:
                findings.append(
                    StaticFinding(
                        path=path,
                        line=node.lineno,
                        problem=f"import from {node.module!r} is not on the allowlist",
                    )
                )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                findings.append(
                    StaticFinding(
                        path=path,
                        line=node.lineno,
                        problem=f"call to {func.id}() grants arbitrary execution",
                    )
                )
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            findings.append(
                StaticFinding(
                    path=path,
                    line=node.lineno,
                    problem=f"access to {node.attr!r} reaches interpreter internals",
                )
            )

    return tuple(findings)
