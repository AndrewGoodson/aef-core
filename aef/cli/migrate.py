"""`aef migrate` — generate node wrappers for a repo's real LLM call sites.

## Why this exists

`aef adopt` writes documentation, a config template, and a stub whose body is
`raise NotImplementedError`. It reads none of the adopting repo's code. For a
long time the scaffold's own pitch claimed agents "inherit ... without
rebuilding any of it per agent", which was the reverse of true: step 5 of the
checklist adopt generates is *"Convert each call site into a Node function"*,
by hand, for every call site.

This command does the mechanical half of that conversion and, more importantly,
**names the half it cannot do**.

## What it finds, and why that unit

Not raw SDK calls. The useful seam is the adopting repo's **own function that
wraps the vendor SDK** — `call_llm_with_backend`, `ask_claude`, whatever it is
called locally — because that function is where the repo has already put its
retries, budgets, backend selection and logging. Wrapping the raw
`client.messages.create` underneath it would bypass all of that and stand up a
second, dumber path beside a hardened one.

So: a function is a **call site** if its body contains a vendor SDK call. One
generated node per such function.

## What it refuses to pretend

Three shapes are found and **skipped, with the reason recorded**, because
generating something plausible for them would be worse than generating nothing:

- **async functions** — `ModelProvider.complete()` and the node contract are
  sync. A generated wrapper would need an event loop the caller may not have.
- **methods** — they need an instance, and this command cannot know how the
  repo constructs one.
- **generators** — they yield rather than return; a node returns once.

Every skip is reported. A migration tool that silently emits nodes for a third
of the call sites and says nothing about the rest is how you end up believing a
repo is migrated when it is not.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

# Vendor SDK entry points. A function whose body touches one of these is
# wrapping a model call, whatever it happens to be named locally.
_VENDOR_ROOTS = ("anthropic", "openai", "mem0", "cohere", "google.generativeai")
_VENDOR_METHODS = (
    "messages.create",
    "completions.create",
    "chat.completions.create",
    "generate_content",
)

_SKIP_DIRS = {"venv", "node_modules", "build", "dist", "site-packages"}


def _skip(path: Path) -> bool:
    """Skip vendored trees and every dot-directory.

    Dot-directories are excluded wholesale rather than enumerated. The first
    run of this command against a real repo reported four call sites, and
    *two* of them were duplicate copies living in `.codex/worktrees/` — git
    worktrees of the same files. An enumerated denylist would have needed
    `.codex` added by hand, and then the next tool's cache dir after that.
    """
    return any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts)


@dataclass(frozen=True)
class CallSite:
    """One function that wraps a vendor call."""

    module: str
    function: str
    lineno: int
    evidence: str


@dataclass(frozen=True)
class Skipped:
    """A call site found and deliberately NOT wrapped."""

    module: str
    function: str
    lineno: int
    reason: str


@dataclass
class MigrateResult:
    sites: list[CallSite] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    scanned_files: int = 0
    written: Path | None = None

    @property
    def total_found(self) -> int:
        return len(self.sites) + len(self.skipped)


def _dotted(node: ast.AST) -> str:
    """Render an attribute chain (`a.b.c`) so it can be matched as text."""
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _vendor_evidence(fn: ast.AST) -> str | None:
    """The vendor construct this function's body touches, or None."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if not name:
                continue
            root = name.split(".", 1)[0]
            if root in _VENDOR_ROOTS:
                return name
            for method in _VENDOR_METHODS:
                if name.endswith(method):
                    return name
    return None


def _scan_module(path: Path, root: Path) -> tuple[list[CallSite], list[Skipped]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        # Unreadable or not Python-3-parseable. Not a call site, and not worth
        # failing the whole scan over — but do not pretend it was scanned.
        return [], []

    rel = path.relative_to(root)
    module = ".".join(rel.with_suffix("").parts)
    sites: list[CallSite] = []
    skipped: list[Skipped] = []

    # Methods are recorded as skipped rather than ignored: "we saw it and
    # cannot wrap it" is information; silence is not.
    method_lines = {
        child.lineno
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef)
        for child in cls.body
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

    # Prefer the OUTERMOST wrapper, not the function holding the raw SDK call.
    #
    # Reproduced on a real repo: the first version of this scan wrapped
    # `research._llm_client._call_api` — the private function that constructs
    # `anthropic.Anthropic()` — while the repo's actual seam is
    # `call_llm_with_backend`, the public function above it carrying the
    # retries, daily budgets and backend order. Wrapping the inner one bypasses
    # every one of those, which is exactly what this module's docstring says not
    # to do. The docstring was right and the code did the opposite.
    #
    # So: find functions that reach a vendor call transitively within the
    # module, then keep only those nothing else in the module calls.
    direct = {fn.name: ev for fn in functions if (ev := _vendor_evidence(fn)) is not None}
    if not direct:
        return [], []

    calls: dict[str, set[str]] = {}
    for fn in functions:
        named: set[str] = set()
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                target = _dotted(sub.func)
                if target:
                    named.add(target.split(".")[-1])
        calls[fn.name] = named

    reaching = dict(direct)
    for _ in range(len(functions)):  # bounded; converges well before this
        grown = False
        for name, targets in calls.items():
            if name in reaching:
                continue
            hit = targets & reaching.keys()
            if hit:
                reaching[name] = f"{next(iter(sorted(hit)))} (transitively)"
                grown = True
        if not grown:
            break

    called_by_a_reacher = {
        target for name, targets in calls.items() if name in reaching for target in targets
    }
    outermost = {n: ev for n, ev in reaching.items() if n not in called_by_a_reacher}
    chosen = outermost or direct

    for node in functions:
        if node.name not in chosen:
            continue
        evidence = chosen[node.name]
        if isinstance(node, ast.AsyncFunctionDef):
            skipped.append(
                Skipped(
                    module,
                    node.name,
                    node.lineno,
                    "async — the node contract and ModelProvider.complete() are sync",
                )
            )
        elif node.lineno in method_lines:
            skipped.append(
                Skipped(
                    module,
                    node.name,
                    node.lineno,
                    "method — needs an instance this command cannot construct",
                )
            )
        elif any(isinstance(sub, ast.Yield | ast.YieldFrom) for sub in ast.walk(node)):
            skipped.append(
                Skipped(
                    module,
                    node.name,
                    node.lineno,
                    "generator — yields repeatedly; a node returns once",
                )
            )
        else:
            sites.append(CallSite(module, node.name, node.lineno, evidence))

    return sites, skipped


def scan(root: Path) -> MigrateResult:
    """Find every function in `root` whose body wraps a vendor SDK call."""
    result = MigrateResult()
    for path in sorted(root.rglob("*.py")):
        if _skip(path):
            continue
        result.scanned_files += 1
        sites, skipped = _scan_module(path, root)
        result.sites.extend(sites)
        result.skipped.extend(skipped)
    return result


def render(result: MigrateResult, repo_name: str) -> str:
    """The generated module. Every wrapper calls the repo's OWN function."""
    header = f'''"""Generated by `aef migrate` for {repo_name}. Review before use.

One node per call site found — a function whose body touches a vendor SDK.
Each wrapper calls YOUR function; none reimplements it, so whatever retries,
budgets and backend selection you already have still apply.

WHAT THIS FILE IS NOT: a finished migration. Each node below passes the
objective through as a single prompt and stores the result. If your function
takes other arguments, or its result needs shaping into `StateDelta`, that is
yours to write — this file gets the plumbing and the imports right, not the
semantics.

Regenerate with `aef migrate --dir .`; it never overwrites without --force.
"""

from __future__ import annotations

from typing import Any

from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, StateDelta
'''

    if not result.sites:
        return (
            header
            + """

# No wrappable call site was found. See the command's report for what was
# skipped and why — an empty file here is a finding, not a failure.


def build_graph() -> Graph:
    raise NotImplementedError(
        "aef migrate found no wrappable call site in this repo. Nothing was "
        "generated, deliberately, rather than emitting a graph that does nothing."
    )
"""
        )

    body = [header]
    node_ids: list[str] = []
    for site in result.sites:
        node_id = f"{site.module.replace('.', '_')}__{site.function}"
        node_ids.append(node_id)
        body.append(f'''

def {node_id}(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    """Wraps `{site.module}.{site.function}` (line {site.lineno}).

    Detected by: `{site.evidence}`
    """
    from {site.module} import {site.function}

    result: Any = {site.function}(state.objective)
    return StateDelta(working_memory={{"{node_id}": result}}), END
''')

    listed = ",\n        ".join(
        f'"{n}": Node(id="{n}", version="0.1.0", fn={n}, deterministic=False)' for n in node_ids
    )
    body.append(f'''

def build_graph() -> Graph:
    """One node per call site. Edges are NOT generated — how these compose is
    a semantic decision `aef migrate` has no basis to make."""
    return Graph(
        id="{repo_name}",
        version="0.1.0",
        nodes={{
        {listed}
        }},
        edges=[],
        entry_node="{node_ids[0]}",
    )
''')
    return "".join(body)


def run_migrate(target_dir: Path, *, force: bool = False, write: bool = True) -> MigrateResult:
    root = target_dir.resolve()
    result = scan(root)
    if not write:
        return result

    out = root / "aef_migrated.py"
    if out.exists() and not force:
        # Same rule as `aef adopt`: never overwrite. A generated file the
        # operator has since edited is the expensive thing to lose.
        return result
    out.write_text(render(result, root.name), encoding="utf-8")
    result.written = out
    return result


def report(result: MigrateResult) -> str:
    lines = [
        f"scanned {result.scanned_files} Python file(s)",
        f"found {result.total_found} call site(s): "
        f"{len(result.sites)} wrapped, {len(result.skipped)} skipped",
        "",
    ]
    for site in result.sites:
        lines.append(f"  WRAPPED  {site.module}.{site.function}:{site.lineno}  ({site.evidence})")
    for skip in result.skipped:
        lines.append(f"  SKIPPED  {skip.module}.{skip.function}:{skip.lineno}  — {skip.reason}")
    if result.written is not None:
        lines += ["", f"wrote {result.written}"]
    elif result.sites or result.skipped:
        lines += ["", "nothing written (file exists; pass --force to overwrite)"]
    lines += [
        "",
        "This generated the PLUMBING, not the semantics. Every wrapper passes",
        "state.objective as a single prompt and stores the raw result; if your",
        "function takes more than that, the node body is yours to finish.",
    ]
    return "\n".join(lines)
