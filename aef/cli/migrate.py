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

## Two node forms, and which one you get (ADR 0137)

Wrapping the adopter's function preserves everything that function does — and
leaves the model call **invisible to the harness**. A node that calls a
function that builds its own `anthropic.Anthropic()` never touches
`Services.model_provider`, so the policy engine does not see the call, the
fallback chain cannot cover it, the harness login cannot pay for it, and
`aef loop record` captures no `RecordedCall`. The scenario then carries no
cassette, and replay with `on_miss="fail"` has nothing to serve: the gate
reaches the vendor live, or fails for want of a credential and scores 0.

So this command generates one of two forms, decides which by reading the
function, and **says which it chose and why** — for every site, in the report
and in the generated docstring:

- **routed** — the node calls `services.require_model_provider().complete(...)`
  and does *not* call your function. Generated only when the function is a
  thin direct wrapper: undecorated, constructing an unconfigured client
  itself, making exactly one completion call with no loop, no `try`, no
  stream, no `**kwargs` and no other calls — **and passing only keywords
  `CompletionRequest` carries verbatim**.
- **unrouted** — today's wrapper, which calls your function, plus a warning in
  its docstring saying the call is invisible and what that costs.

**The falsification clause, honoured rather than argued.** If the function has
retries, a backend router, a loop, a stream, or does anything else at all,
routing through `ModelProvider.complete()` would silently drop it — a
single-shot, non-streaming call is strictly less than what that function does.
That is a trade, and a generator is the wrong place to make one on the
adopter's behalf. Every such site gets the **unrouted** form with the warning,
and the report names the specific thing that would have been lost. The
conservative direction is deliberate: a wrapper that is honestly labelled
invisible is recoverable; a rewrite that quietly dropped a retry policy is
found in production.

**And the clause covers the request, not only the control flow (ADR 0140).**
Its first version enumerated retries, streams and backends and never asked
whether the *request* survives translation. `CompletionRequest` has five
fields. A call passing `system=`, `tools=` or `stop_sequences=` was routed,
and there is no field for any of them — so "yours to re-express" named a place
that does not exist, while the generated docstring said "there is nothing here
for routing to lose". (`ProviderMessage` carries a `system` role that both
adapters fold in, so a system prompt is *representable*; synthesising one to
pair with the substituted objective is a semantic decision, which is why this
command refuses rather than guesses.) The routable set of keywords is read off
`dataclasses.fields(CompletionRequest)`, so a field added to the request type
widens it on the same commit and a second hardcoded list cannot drift from it.

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
import json
import textwrap
from dataclasses import dataclass, field, fields
from pathlib import Path

from aef.harness.vendor_scan import MODEL_SDK_ROOTS, SKIP_DIRS
from aef.providers.base import CompletionRequest

# The keywords a routed node can actually carry, derived from the request type
# **itself** rather than from a second hand-written list.
#
# ADR 0140. The routable predicate used to judge control flow only — no loop,
# no try, no stream — and never asked whether the *request* survives the
# translation. A call passing `system=`, `tools=` or `stop_sequences=` was
# routed, and `CompletionRequest` has no field for any of them, so they were
# dropped with nowhere to put them back. Reading the field names off the
# dataclass means a field added to `CompletionRequest` tomorrow widens this
# predicate on the same commit; a hardcoded copy here is the drift ADR 0091
# is about, and it is the drift that produced this defect.
_REQUEST_FIELDS: frozenset[str] = frozenset(f.name for f in fields(CompletionRequest)) | {
    "messages"
}

# Same source, in declaration order, minus the one the generated node supplies
# from `state.objective` rather than from the call site.
_CARRIED_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(CompletionRequest) if f.name != "messages"
)

# Vendor SDK entry points. A function whose body touches one of these is
# wrapping a model call, whatever it happens to be named locally.
#
# The roots come from `aef/harness/vendor_scan.py`, which is also what
# `tests/test_vendor_isolation.py` and the preflight obligation scan with. A
# second list of vendor module names here is the drift ADR 0091 is about.
_VENDOR_METHODS = (
    "messages.create",
    "completions.create",
    "chat.completions.create",
    "generate_content",
)


def _skip(rel: Path) -> bool:
    """Skip vendored trees and every dot-directory.

    Dot-directories are excluded wholesale rather than enumerated. The first
    run of this command against a real repo reported four call sites, and
    *two* of them were duplicate copies living in `.codex/worktrees/` — git
    worktrees of the same files. An enumerated denylist would have needed
    `.codex` added by hand, and then the next tool's cache dir after that.

    **The path is tested relative to the scan root.** It was tested absolutely
    until ADR 0137, which meant a repo that itself lived under any
    dot-directory — `~/.local/src/app`, a git worktree under `.claude/`, a
    checkout in `.build/` — had *every* file skipped and was reported as
    `scanned 0 Python file(s) ... 0 call site(s)`, exit 0. The tool said the
    repo had no model calls because it had refused to look at the repo.
    """
    return any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts)


@dataclass(frozen=True)
class CallSite:
    """One function that wraps a vendor call, and which form it gets."""

    module: str
    function: str
    lineno: int
    evidence: str
    # ADR 0137. `routed` is the choice; `form_reason` is why, and is carried
    # into both the report and the generated docstring so the adopter reads
    # the same sentence in both places.
    routed: bool = False
    form_reason: str = ""
    model: str | None = None
    max_tokens: int | None = None
    # Every keyword the call site passed that `CompletionRequest` can carry,
    # already rendered as source, in the request type's own field order. A
    # routed node emits exactly these and nothing else — if the call passed
    # anything this tuple cannot hold, it is not routed at all (ADR 0140).
    request_args: tuple[tuple[str, str], ...] = ()


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
    # Set when `--force` overwrote a file that differed from what migrate
    # would have generated — i.e. one somebody edited (ADR 0140).
    backup: Path | None = None

    @property
    def total_found(self) -> int:
        return len(self.sites) + len(self.skipped)

    @property
    def routed(self) -> list[CallSite]:
        return [s for s in self.sites if s.routed]

    @property
    def unrouted(self) -> list[CallSite]:
        return [s for s in self.sites if not s.routed]


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


def _is_completion_call(name: str) -> bool:
    return any(name.endswith(method) for method in _VENDOR_METHODS)


def _vendor_evidence(fn: ast.AST) -> str | None:
    """The vendor construct this function's body touches, or None."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if not name:
                continue
            root = name.split(".", 1)[0]
            if root in MODEL_SDK_ROOTS:
                return name
            if _is_completion_call(name):
                return name
    return None


@dataclass(frozen=True)
class _Routing:
    """The routed/unrouted decision for one function, and its reason."""

    routed: bool
    reason: str
    model: str | None = None
    max_tokens: int | None = None
    request_args: tuple[tuple[str, str], ...] = ()


def _render_literal(node: ast.AST) -> str | None:
    """The call site's literal value as source a generated node can carry, or
    `None` if it is not a literal this command will reproduce verbatim.

    "Verbatim" is the bar, not "close enough". A `max_tokens=MAX` routed as
    `max_tokens=<the request type's default>` is the same silent substitution
    as dropping `system=`, one step quieter.
    """
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, str):
        # json.dumps, not repr: double quotes and ASCII-safe escapes, both of
        # which are valid Python and match the rest of the generated file.
        return json.dumps(value)
    if isinstance(value, int | float):
        return repr(value)
    return None


def _decorator_names(fn: ast.AST) -> list[str]:
    decorators = getattr(fn, "decorator_list", [])
    names = []
    for dec in decorators:
        rendered = _dotted(dec.func) if isinstance(dec, ast.Call) else _dotted(dec)
        names.append(rendered or "<expression>")
    return names


def _routing_decision(fn: ast.AST, *, direct: bool) -> _Routing:
    """Can this function's model call be routed through `Services` without
    losing something the function already does?

    Every `False` below names a specific thing routing would have dropped.
    That is the point: the falsification clause in ADR 0137 says a routed form
    that loses retries or streaming is a silent rewrite, so the answer when
    anything at all is in the way is the unrouted form plus a warning.

    ADR 0140 widened "anything at all" in four directions, each reproduced
    against a routed node that dropped something real: the request's own
    keywords (`system=`, `tools=`, ...), decorators, `**kwargs` forwarding,
    and a client constructed with arguments. ADR 0137's clause enumerated
    retries, streams and backends — control flow — and never asked whether the
    **request** survives translation into `CompletionRequest`.
    """
    if not direct:
        return _Routing(
            False,
            "it wraps another function that reaches the SDK — whatever retries, budgets "
            "and backend order live down there would be dropped by routing",
        )

    # A decorator is not visible in the body, and this analysis reads bodies.
    # REPRODUCED: a bare `@retry` (an `ast.Name`, not an `ast.Call`) slipped
    # past every rule below — including the "body also calls retry()" one,
    # which only ever caught `@retry(...)` by accident, because a *called*
    # decorator leaves a `Call` node in `decorator_list` for `ast.walk` to
    # find. Retries were dropped, silently, for the bare form.
    decorators = _decorator_names(fn)
    if decorators:
        shown = ", ".join(f"@{name}" for name in decorators)
        return _Routing(
            False,
            f"it is decorated ({shown}) — a decorator can wrap the call in retry, caching, "
            f"rate limiting or tracing that the body does not show, and routing keeps only "
            f"the body",
        )

    calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call)]
    names = [(node, _dotted(node.func)) for node in calls]
    named = [(node, name) for node, name in names if name]

    constructions = [
        (node, name) for node, name in named if name.split(".", 1)[0] in MODEL_SDK_ROOTS
    ]
    if not constructions:
        return _Routing(
            False,
            "the client is injected or global rather than built here — migrate cannot see "
            "which vendor or which model this call uses",
        )

    for node in ast.walk(fn):
        if isinstance(node, ast.Try):
            return _Routing(
                False,
                "its body catches exceptions — a retry or fallback policy that a single "
                "complete() call would silently drop",
            )
        if isinstance(node, ast.For | ast.AsyncFor | ast.While):
            return _Routing(
                False,
                "its body loops — a retry, backoff or pagination policy that a single "
                "complete() call would silently drop",
            )

    # A client built with arguments is a configured client. REPRODUCED with
    # the corporate-gateway shape —
    # `anthropic.Anthropic(base_url="https://llm-gateway.corp/v1",
    # timeout=120.0, max_retries=8)` — which routed happily, so the generated
    # node quietly reached a different endpoint, on a different credential,
    # billed to a different account, with the SDK's own retry policy gone.
    # None of that is expressible through `Services.model_provider`, which
    # resolves its own endpoint and key.
    for node, name in constructions:
        parts = [f"{kw.arg}=" for kw in node.keywords if kw.arg is not None]
        if any(kw.arg is None for kw in node.keywords):
            parts.append("**kwargs")
        if node.args:
            parts.append("positional argument(s)")
        if parts:
            return _Routing(
                False,
                f"it configures its own client — {name}({', '.join(parts)}) sets an endpoint, "
                f"credential, timeout or retry policy that Services.model_provider resolves "
                f"for itself, so routing would send this call somewhere else",
            )

    if any(name.endswith(".stream") or name.endswith(".stream_async") for _, name in named):
        return _Routing(
            False,
            "it streams its reply — ModelProvider.complete() returns once, so routing "
            "would change the shape of the answer your caller reads",
        )

    unknown = sorted(
        {
            name
            for _, name in named
            if name.split(".", 1)[0] not in MODEL_SDK_ROOTS and not _is_completion_call(name)
        }
    )
    if unknown:
        return _Routing(
            False,
            f"its body also calls {unknown[0]}() — it does more than make the call, and "
            f"migrate cannot tell what routing would drop",
        )

    completions = [node for node, name in named if _is_completion_call(name)]
    if not completions:
        return _Routing(
            False,
            "its body constructs a client but makes no completion call migrate recognises, "
            "so there is no request to rebuild",
        )
    if len(completions) > 1:
        return _Routing(
            False,
            f"its body makes {len(completions)} completion calls — a node returns once, and "
            f"which of them is the answer is a semantic decision",
        )

    call = completions[0]

    # REPRODUCED: `client.messages.create(..., **kwargs)` routed, because
    # `ast.keyword` with `arg=None` was filtered out one line below and the
    # rest of the call looked thin. Whatever a caller passes at runtime —
    # `stream=True`, `system=`, `tools=` — is then dropped without trace, and
    # the stream check above is defeated by a caller rather than by the code.
    forwarded = []
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        forwarded.append("*args")
    if any(kw.arg is None for kw in call.keywords):
        forwarded.append("**kwargs")
    if forwarded:
        return _Routing(
            False,
            f"it forwards {' and '.join(forwarded)} into the SDK call — migrate cannot see "
            f"what a caller passes, so a caller supplying stream=, system= or tools= at "
            f"runtime would have it dropped without trace",
        )

    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}

    stream = kwargs.get("stream")
    if stream is not None and not (isinstance(stream, ast.Constant) and stream.value is False):
        return _Routing(
            False,
            "it passes stream= to the SDK — ModelProvider.complete() returns once, so "
            "routing would change the shape of the answer your caller reads",
        )

    # THE REQUEST ITSELF. Everything above this line judges control flow;
    # ADR 0137 stopped here and called the result "nothing to lose". A call
    # passing `system="You are a claims adjuster. NEVER approve a payout above
    # $5,000."` alongside `tools=` and `stop_sequences=` was routed, and
    # `CompletionRequest` has no field for any of the three — so the generated
    # docstring's "yours to re-express" named a place that does not exist.
    # (`ProviderMessage` does carry a `system` ROLE, which both adapters fold
    # into the vendor's system parameter — but this node replaces the whole
    # message list with `state.objective`, so pairing a literal system prompt
    # with a substituted user turn is a semantic decision, not plumbing.)
    #
    # `stream` is excluded because it has its own refusal above; the only
    # value that reaches here is a literal `stream=False`, which routing
    # preserves exactly rather than drops.
    inexpressible = sorted(
        {name for name in kwargs if name not in _REQUEST_FIELDS and name != "stream"}
    )
    if inexpressible:
        # `system=` is named on its own: it is not a tuning knob, it is the
        # instruction the adopter's behaviour depends on.
        if "system" in inexpressible:
            others = [f"{name}=" for name in inexpressible if name != "system"]
            also = f" (and {', '.join(others)})" if others else ""
            return _Routing(
                False,
                f"it passes system= to the SDK{also} — a system prompt is an instruction your "
                f"code relies on, and CompletionRequest has no system field; carrying it would "
                f"mean synthesising a system-role message to pair with the objective this node "
                f"substitutes, which is a semantic decision migrate will not make for you",
            )
        listed = ", ".join(f"{name}=" for name in inexpressible)
        them = "them" if len(inexpressible) > 1 else "it"
        return _Routing(
            False,
            f"it passes {listed} to the SDK, and CompletionRequest cannot express {them} — "
            f"routing would drop {them} with nowhere to re-express {them}",
        )

    model = kwargs.get("model")
    if not (isinstance(model, ast.Constant) and isinstance(model.value, str)):
        return _Routing(
            False,
            "the model id is not a literal at this call — migrate will not guess which "
            "model your code asks for",
        )

    # Expressible is necessary and not sufficient: the value has to be one this
    # command can reproduce verbatim. `max_tokens=MAX` used to be routed as no
    # max_tokens at all, which silently substituted the request type's default.
    request_args: list[tuple[str, str]] = []
    for name in _CARRIED_FIELDS:
        value = kwargs.get(name)
        if value is None:
            continue
        rendered = _render_literal(value)
        if rendered is None:
            return _Routing(
                False,
                f"its {name}= is not a literal at this call, so routing would have to guess "
                f"the value or drop it — and CompletionRequest.{name} has a default that "
                f"would silently take its place",
            )
        request_args.append((name, rendered))

    max_tokens_node = kwargs.get("max_tokens")
    max_tokens = (
        max_tokens_node.value
        if isinstance(max_tokens_node, ast.Constant) and isinstance(max_tokens_node.value, int)
        else None
    )
    return _Routing(
        True,
        "its body builds an unconfigured client and makes exactly one completion call — no "
        "decorator, no loop, no try/except, no stream, no **kwargs, and every keyword it "
        "passes is one CompletionRequest carries verbatim",
        model=model.value,
        max_tokens=max_tokens,
        request_args=tuple(request_args),
    )


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
            routing = _routing_decision(node, direct=node.name in direct)
            sites.append(
                CallSite(
                    module,
                    node.name,
                    node.lineno,
                    evidence,
                    routed=routing.routed,
                    form_reason=routing.reason,
                    model=routing.model,
                    max_tokens=routing.max_tokens,
                    request_args=routing.request_args,
                )
            )

    return sites, skipped


def scan(root: Path) -> MigrateResult:
    """Find every function in `root` whose body wraps a vendor SDK call."""
    result = MigrateResult()
    for path in sorted(root.rglob("*.py")):
        if _skip(path.relative_to(root)):
            continue
        result.scanned_files += 1
        sites, skipped = _scan_module(path, root)
        result.sites.extend(sites)
        result.skipped.extend(skipped)
    return result


_NO_SITES_BODY = """
# No wrappable call site was found. See the command's report for what was
# skipped and why — an empty file here is a finding, not a failure.


def build_graph() -> Graph:
    raise NotImplementedError(
        "aef migrate found no wrappable call site in this repo. Nothing was "
        "generated, deliberately, rather than emitting a graph that does nothing."
    )
"""


_DOCSTRING = """
One node per call site found — a function whose body touches a vendor SDK.

TWO FORMS, AND THIS FILE SAYS WHICH IT CHOSE. A node marked ROUTED asks
`services.require_model_provider()` and does NOT call your function: the call
is then visible to the policy engine, the fallback chain and the harness
cassette, and whatever CONTROL FLOW your function had around the call is yours
to re-express. Its REQUEST is carried, not re-expressed: a call is routed only
when every keyword it passed is one `CompletionRequest` carries verbatim, and
those keywords are reproduced in the node body. A node marked UNROUTED calls
your function unchanged — nothing is lost, and the model call stays invisible
to the harness, which is stated in that node's own docstring rather than left
to be discovered at gate time.

EVERY NODE HERE DECLARES `side_effects=SideEffect.EXTERNAL_CALL`, because
every one of them reaches a model. See `_idempotency_key` below for what the
key that declaration requires does and does not buy you.

WHAT THIS FILE IS NOT: a finished migration. Each node below passes the
objective through as a single prompt and stores the result. If your function
takes other arguments, or its result needs shaping into `StateDelta`, that is
yours to write — this file gets the plumbing and the imports right, not the
semantics. The routed/unrouted choice is likewise a reading of your code, not
a judgement about it: re-route an UNROUTED node by hand once you have decided
what its retries and backend selection should become.

Regenerate with `aef migrate --dir .`; it never overwrites without --force.
\"\"\"

"""


def _header(result: MigrateResult, repo_name: str) -> str:
    """The module docstring and imports.

    Imports are conditional on which forms were actually generated. An unused
    `from typing import Any` is an `F401` in the adopter's own lint run, and a
    generated file that fails the lint of the repo it lands in is a chore
    handed over rather than work done.
    """
    docstring = f'"""Generated by `aef migrate` for {repo_name}. Review before use.\n' + _DOCSTRING

    imports = ["from __future__ import annotations", ""]
    if not result.sites:
        # The refusal body defines `build_graph()` and nothing else, so every
        # other name would be unused. This imported all eight of them.
        return docstring + "\n".join(imports + ["from aef.kernel import Graph"]) + "\n"
    imports += ["from collections.abc import Callable"]
    if result.unrouted:
        imports += ["from typing import Any"]
    imports += ["", "from aef.kernel import END, Context, Graph, Node, Route, Services, SideEffect"]
    if result.routed:
        imports += ["from aef.providers.base import CompletionRequest, ProviderMessage"]
    imports += ["from aef.state import AEFState, StateDelta"]

    return docstring + "\n".join(imports) + "\n"


_KEY_FN = '''

def _idempotency_key(node_id: str) -> Callable[[AEFState], str]:
    """The key the executor computes ONCE per node execution (ADR 0010).

    Every node in this file declares `side_effects=SideEffect.EXTERNAL_CALL`,
    because every one of them reaches a model — and the node contract requires
    an `idempotency_key_fn` from anything that is not pure. Before ADR 0140
    these nodes declared nothing, so they defaulted to PURE: a live model call
    labelled as having no effect on the world.

    This generator supplies the key rather than leaving the file unbuildable,
    and this docstring is what you are owed in exchange for a choice made on
    your behalf:

    - The key is stable across the attempts of ONE execution and differs
      between executions, which is what makes a repeat traceable to its cause.
    - It does NOT make repeating the call free. `ModelProvider.complete()`
      accepts no idempotency key, so nothing downstream deduplicates on this
      one: a second attempt is a second billed call returning a different
      answer. `aef`'s bounded-retry transformation reads the declaration on
      each node below, and will now propose retrying it — decide whether that
      is acceptable for your model spend before accepting such a candidate.
    """
    return lambda state: f"{node_id}:{state.run_id}:{state.checkpoint_seq}"
'''


def _key_fn_kwarg(node_id: str, indent: str) -> str:
    """The `idempotency_key_fn=` line, wrapped if the node id is long enough
    to push it past 100 columns. A generated file that fails the lint of the
    repo it lands in is a chore handed over, and node ids are derived from the
    adopter's module paths — `src_services_llm_client__call_with_backend` is
    an ordinary one and is 44 characters.
    """
    one_line = f'{indent}idempotency_key_fn=_idempotency_key("{node_id}"),'
    if len(one_line) <= 100:
        return one_line
    return f'{indent}idempotency_key_fn=_idempotency_key(\n{indent}    "{node_id}"\n{indent}),'


def _wrap(text: str, *, indent: str = "    ") -> str:
    """Reflow a reason into the generated docstring inside 100 columns.

    The reasons are whole sentences on purpose — an adopter reads them in the
    report and in the node they landed on — and one of them is 171 characters.
    A generated file that fails the lint of the repo it lands in is a chore
    handed over, so the width is enforced here rather than hoped for.
    """
    return textwrap.fill(text, width=100, initial_indent=indent, subsequent_indent=indent).lstrip()


def _render_routed(site: CallSite, node_id: str) -> str:
    # Every keyword the call site passed, verbatim — not a chosen subset. The
    # predicate refuses to route at all unless this tuple is the whole of it.
    carried = "".join(f"\n            {name}={value}," for name, value in site.request_args)
    reason = _wrap(f"Routed because {site.form_reason}.")
    replaces = _wrap(f"Replaces `{site.module}.{site.function}` (line {site.lineno}).")
    bypassed = _wrap(
        f"`{site.module}.{site.function}` IS NOT CALLED by this node — it is bypassed."
    )
    return f'''

def {node_id}(
    state: AEFState, ctx: Context, services: Services
) -> tuple[StateDelta, Route]:
    """ROUTED node for one of this repo's model call sites.

    {replaces}
    Detected by: `{site.evidence}`
    {reason}

    {bypassed}
    Its control flow around the call (retries, budget accounting, backend
    selection, logging) is now yours to re-express here. Its REQUEST is not:
    migrate routes a call only when every keyword it passed is one
    `CompletionRequest` carries verbatim, and the keywords it passed are
    reproduced below. A call carrying anything else — `system=`, `tools=`,
    `stop_sequences=` — is never routed at all, rather than routed without it
    (ADR 0140).

    What you get for the bypass is a call the harness can see: the policy
    engine gates it, the fallback chain covers it, the harness login pays for
    it, and `aef loop record` captures it so the gates can replay the scenario
    without a credential.
    """
    result = services.require_model_provider().complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content=state.objective),),{carried}
        )
    )
    key = "{node_id}"
    return StateDelta(working_memory={{key: result.content}}), END
'''


def _render_unrouted(site: CallSite, node_id: str) -> str:
    reason = _wrap(f"Not routed because {site.form_reason}.")
    wraps = _wrap(f"Wraps `{site.module}.{site.function}` (line {site.lineno}), unchanged.")
    # A deep module path plus a long function name pushes a one-line import
    # past 100 columns, and the adopter's own ruff run is where that lands.
    import_line = f"    from {site.module} import {site.function}"
    if len(import_line) > 100:
        import_line = f"    from {site.module} import (\n        {site.function},\n    )"
    return f'''

def {node_id}(
    state: AEFState, ctx: Context, services: Services
) -> tuple[StateDelta, Route]:
    """UNROUTED wrapper for one of this repo's model call sites.

    {wraps}
    Detected by: `{site.evidence}`
    {reason}

    WARNING — this node calls your function, and your function reaches the
    vendor SDK itself. That call does NOT pass through
    `Services.model_provider`, so the policy engine never sees it, the
    fallback chain cannot cover it, and it still needs your own API key.
    `aef loop record` captures no RecordedCall for it either, so any scenario
    recorded from this node carries an empty cassette and replay with
    on_miss="fail" has nothing to serve — the gates will reach the vendor live
    or score the scenario 0.

    Routing it is a trade, not a free win: see the reason above for what
    `complete()` would have dropped. Decide it deliberately, then rewrite this
    body to call `services.require_model_provider().complete(...)`.
    """
{import_line}

    result: Any = {site.function}(state.objective)
    key = "{node_id}"
    return StateDelta(working_memory={{key: result}}), END
'''


def render(result: MigrateResult, repo_name: str) -> str:
    """The generated module. One node per call site, in one of two forms."""
    header = _header(result, repo_name)
    if not result.sites:
        return header + _NO_SITES_BODY

    body = [header, _KEY_FN]
    node_ids: list[str] = []
    for site in result.sites:
        node_id = f"{site.module.replace('.', '_')}__{site.function}"
        node_ids.append(node_id)
        body.append(
            _render_routed(site, node_id) if site.routed else _render_unrouted(site, node_id)
        )

    # ADR 0140: `side_effects` was omitted entirely, so every generated node
    # defaulted to `SideEffect.PURE` — a live model call declared to have no
    # effect on the world. `add_bounded_retry` reads that declaration from
    # source before wrapping a node in a 3-attempt retry, and its own comment
    # says it "requires the declaration rather than assuming it"; the
    # generator had never written one, so the guard was asking a question
    # nobody had answered and getting the safest-sounding wrong answer.
    listed = "\n".join(
        f'            "{n}": Node(\n'
        f'                id="{n}",\n'
        f'                version="0.1.0",\n'
        f"                fn={n},\n"
        f"                deterministic=False,\n"
        f"                side_effects=SideEffect.EXTERNAL_CALL,\n"
        f"{_key_fn_kwarg(n, '                ')}\n"
        f"            ),"
        for n in node_ids
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


def _backup_path(out: Path) -> Path:
    """A `.bak` beside the file that never destroys an earlier one.

    Overwriting `aef_migrated.py.bak` on a second `--force` would lose the
    first round of edits to save the second, which is the same failure one
    step along.
    """
    candidate = out.with_suffix(out.suffix + ".bak")
    counter = 1
    while candidate.exists():
        candidate = out.with_suffix(f"{out.suffix}.bak.{counter}")
        counter += 1
    return candidate


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

    rendered = render(result, root.name)

    # ADR 0140. `--force` used to discard hand edits silently and exit 0 —
    # while `aef loop doctor`'s fix string for the "model calls visible"
    # obligation printed `aef migrate --dir . --force` as the recommended
    # next command. The comment three lines above named the edited file as
    # "the expensive thing to lose" and then `--force` lost it. Compare
    # against what migrate WOULD generate: identical means there is nothing
    # to preserve, different means somebody changed it.
    if out.exists():
        try:
            existing = out.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            existing = None
        if existing is not None and existing != rendered:
            backup = _backup_path(out)
            backup.write_text(existing, encoding="utf-8")
            result.backup = backup

    out.write_text(rendered, encoding="utf-8")
    result.written = out
    return result


def report(result: MigrateResult) -> str:
    lines = [
        f"scanned {result.scanned_files} Python file(s)",
        f"found {result.total_found} call site(s): "
        f"{len(result.sites)} wrapped, {len(result.skipped)} skipped",
    ]
    if result.sites:
        lines.append(
            f"  of the wrapped: {len(result.routed)} routed through "
            f"Services.model_provider, {len(result.unrouted)} still calling your function"
        )
    lines.append("")
    for site in result.sites:
        label = "ROUTED " if site.routed else "WRAPPED"
        lines.append(f"  {label}  {site.module}.{site.function}:{site.lineno}  ({site.evidence})")
        if site.routed:
            lines.append(
                f"            -> services.require_model_provider().complete(model={site.model!r})"
            )
            lines.append(f"            routed because {site.form_reason}")
            lines.append(
                f"            {site.module}.{site.function} is now BYPASSED — its retries "
                f"and backend selection are yours to re-express"
            )
        else:
            lines.append(f"            -> calls {site.module}.{site.function}, unchanged")
            lines.append(f"            NOT routed because {site.form_reason}")
            lines.append(
                "            the model call stays INVISIBLE to the harness: no policy "
                "check, no fallback, no RecordedCall to replay"
            )
    for skip in result.skipped:
        lines.append(f"  SKIPPED  {skip.module}.{skip.function}:{skip.lineno}  — {skip.reason}")
    if result.backup is not None:
        lines += [
            "",
            "your existing aef_migrated.py DIFFERED from what migrate generates —",
            f"it was backed up to {result.backup} before being overwritten.",
            "If you had hand-edited it (re-expressed a system prompt, finished a",
            "node body), that work is in the backup and not in the new file.",
        ]
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
    if result.unrouted:
        lines += [
            "",
            "Every UNROUTED node above leaves its model call invisible to the",
            "harness. `aef loop doctor` reports that as an unmet obligation, and",
            "it is not a false alarm: the gates cannot replay a call they never",
            "saw. Routing one by hand is a trade — read the reason it was not",
            "routed automatically before you make it.",
        ]
    return "\n".join(lines)
