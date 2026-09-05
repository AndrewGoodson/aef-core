"""`make_prompt_agent_node` — a prompt-file agent, run as one graph node.

## Why this exists

Every eligible repo the 2026-09-04 survey looked at had **zero SDK call
sites**: its agents are `.claude/agents/*.md` persona files run *by a coding
harness*, not Python that calls `anthropic`. `aef migrate` scans for functions
whose bodies touch a vendor SDK, so on those repos it found nothing and said
so, and `CLAUDE.md` concluded the runtime "has nothing to attach to at the
agent layer". `ClaudeCodeProvider` (ADR 0112) removed the premise of that
sentence — a node's model call is one headless `claude -p` under the harness's
own login — but nothing turned a persona file into a node. This does.

## The safety property, stated because it is the whole point

**The prompt runs; the agent's tools do not.**

The persona body becomes a `system` message on one `CompletionRequest`. It
reaches the model through `Services.model_provider`, and the harness adapters
send `--tools ""` with `--max-turns 1` (`ClaudeCodeProvider`), so the run is a
single tool-less completion. A persona that says "read the repo, edit the
config, call the Accela API" produces *text describing* that; nothing in this
path can open a file, spawn a process or reach a network service. The
frontmatter's own `tools:` key is read and **deliberately not honoured** — it
is reported, never obeyed — because honouring it would be this module handing
an untrusted markdown file a capability grant, which is exactly what
`PolicyEngine`'s deny-by-default exists to refuse (constraint #6).

That is a real reduction in what the agent can do, and it is stated here
rather than discovered: a migrated persona is a *reasoner over the objective*,
not the tool-using session the persona was written for.

## What is parsed, and what is not

Only `name` and `description` are read out of the YAML frontmatter, with a
line-oriented reader rather than a YAML parse. Two reasons, and neither is
"YAML is hard": the body below the fence is the payload and is passed through
byte-for-byte, so a partial frontmatter read cannot corrupt it; and every
other frontmatter key in the wild (`tools`, `model`, `color`, `allowed-tools`)
is a capability or routing hint this node must not act on, so *not* having
them in a dict is the cheapest way to not act on them.

A file with no frontmatter is still an agent: its name falls back to the
filename stem and the whole file is the body. A file with a frontmatter fence
and no `name` does the same. Neither is an error, because a persona that a
harness would happily run is not made invalid by this runtime's preferences.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from aef.kernel.contracts import Context, Node, Route, Services, SideEffect
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.state import AEFState, Plan, Provenance, StateDelta

FRONTMATTER_FENCE = "---"

# The conventional location. Not a configurable set: `aef migrate` takes the
# directory as an argument, and this constant is what it defaults to.
DEFAULT_PROMPT_AGENT_DIR = ".claude/agents"

# Written by `aef migrate` under the agent root. Excluded from discovery so a
# second `migrate` never treats its own output as an agent to migrate.
MIGRATED_DIR_NAME = "migrated"


class PromptAgentError(RuntimeError):
    """The prompt file could not be found or read at execution time.

    Raised rather than substituted-for. A node that quietly ran with an empty
    system prompt would produce a plausible answer from no persona at all, and
    the run would be scored as if the agent had been consulted.
    """


@dataclass(frozen=True)
class PromptAgentDefinition:
    """One persona file, parsed. `body` is the system prompt, verbatim."""

    name: str
    description: str
    body: str
    # Repo-relative POSIX path, or "" when the definition was built from text
    # with no file behind it (the tests do this).
    source: str = ""
    # Frontmatter keys seen and NOT acted on. Reported by `aef migrate` so the
    # adopter is told what the migration dropped, rather than discovering it.
    unhonoured_keys: tuple[str, ...] = ()


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """`(frontmatter lines, body)`.

    The fence must be the very first line; a `---` further down a markdown
    file is a horizontal rule, and treating one as a frontmatter opener would
    swallow the top of somebody's prompt into metadata.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return [], text
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_FENCE:
            return lines[1:index], "\n".join(lines[index + 1 :]).lstrip("\n")
    # An opening fence with no closing one. The file is malformed as
    # frontmatter, so it is read as a body — losing a prompt to a typo in a
    # delimiter is the worse failure.
    return [], text


def _frontmatter_scalars(lines: list[str]) -> dict[str, str]:
    """Top-level `key: value` pairs only.

    Indented lines (a nested mapping, a list item) are skipped rather than
    interpreted: this reader exists to find two strings, and anything it
    cannot read as one string it reports as present and unread.
    """
    found: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.startswith(("#", " ", "\t", "-")):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        found[key] = value.strip().strip("'\"")
    return found


def parse_agent_file(text: str, *, fallback_name: str = "agent") -> PromptAgentDefinition:
    """Parse one persona file's text. Never raises: see the module docstring."""
    lines, body = _split_frontmatter(text)
    scalars = _frontmatter_scalars(lines)
    name = scalars.get("name") or fallback_name
    unhonoured = tuple(sorted(k for k in scalars if k not in ("name", "description")))
    return PromptAgentDefinition(
        name=name,
        description=scalars.get("description", ""),
        body=body.strip(),
        unhonoured_keys=unhonoured,
    )


def load_agent_file(path: Path, *, source: str = "") -> PromptAgentDefinition:
    definition = parse_agent_file(path.read_text(encoding="utf-8"), fallback_name=path.stem)
    return PromptAgentDefinition(
        name=definition.name,
        description=definition.description,
        body=definition.body,
        source=source or path.name,
        unhonoured_keys=definition.unhonoured_keys,
    )


def resolve_agent_file(agent_file: str, module_file: str | None = None) -> Path:
    """Find the persona file a generated graph names.

    The generated module carries a **repo-relative** path, because that is the
    only spelling that survives being copied into a candidate workspace: the
    gates materialise the base tree plus the Zone A overlay into a fresh
    directory, so an absolute path baked at migrate time would point at the
    adopter's checkout while the graph under test ran somewhere else.

    Repo-relative then has to be resolved against something. The working
    directory is tried first (`aef run` is documented to run from the repo
    root, and the sandbox runs the workspace root). If that misses, the
    generated module's own location is walked upwards — `<root>/<agent
    root>/migrated/<name>/graph.py` is always some number of levels below the
    root that also contains `.claude/agents/...`. Every path tried is named in
    the error, because "prompt file not found" without the list is a bug
    report nobody can act on.
    """
    candidate = Path(agent_file)
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate
        raise PromptAgentError(f"prompt agent file not found: {candidate}")

    tried: list[Path] = []
    here = (Path.cwd() / candidate).resolve()
    tried.append(here)
    if here.is_file():
        return here
    if module_file:
        for parent in Path(module_file).resolve().parents:
            option = parent / candidate
            tried.append(option)
            if option.is_file():
                return option
    raise PromptAgentError(
        f"prompt agent file {agent_file!r} not found. Tried: "
        + ", ".join(str(t) for t in tried)
        + ". The path is repo-relative; run from the repository root, or "
        "regenerate the graph with `aef migrate`."
    )


def prompt_agent_idempotency_key(agent_name: str, objective: str) -> str:
    """The key the node contract requires of an `EXTERNAL_CALL` node.

    From **(agent name, objective)** and nothing else, which is the honest
    scope: the same persona asked the same question is the same call, and two
    attempts at it are the repeat this key exists to make traceable. The
    objective is hashed rather than embedded — objectives are prose, and a key
    is compared and logged, not read.

    It does NOT make the call free to repeat. `ModelProvider.complete()`
    accepts no idempotency key, so nothing downstream deduplicates on this
    one; a second attempt is a second billed harness run (the same caveat
    `aef migrate`'s generated `_idempotency_key` carries).
    """
    digest = hashlib.sha256(objective.encode("utf-8")).hexdigest()[:16]
    return f"prompt_agent:{agent_name}:{digest}"


def make_prompt_agent_node(
    *,
    agent_file: str = "",
    agent_name: str = "",
    definition: PromptAgentDefinition | None = None,
    module_file: str | None = None,
    node_id: str = "prompt_agent",
    version: str = "0.1.0",
    route: Route = "reflect",
) -> Node:
    """A `Node` that runs one persona file as a single tool-less completion.

    **The prompt runs; the agent's tools do not.** The persona body is the
    `system` message, `state.objective` is the user turn, and the harness
    adapters issue `--tools ""` with `--max-turns 1` — so a persona written
    for a tool-using session becomes a reasoner over the objective and touches
    nothing. The frontmatter's `tools:` key is read and never honoured.

    Pass `agent_file` (repo-relative, the form `aef migrate` generates) to
    read the persona at execution time, or `definition` to supply one
    directly. Reading at execution time is what lets ADR 0152's Zone A
    widening mean anything: a proposer that edits the `.md` changes what the
    next run sends, with no regeneration step in between.

    `route` defaults to `"reflect"` rather than `END`, and that default is
    load-bearing: the reflect node is the only thing that writes the failure
    memory the self-rewiring loop's proposer reads. Routed to `END` the loop
    does not break, it goes silent — `aef loop cycle` exits 0 with `no
    admissible failure memory` forever (ADR 0139/0143).

    `model` is left empty so the provider's configured default answers, which
    is what lets one recording replay under another default (ADR 0123).
    """
    if definition is None and not agent_file:
        raise PromptAgentError(
            "make_prompt_agent_node needs either agent_file= (a repo-relative persona "
            "path) or definition= (an already-parsed one); it was given neither"
        )

    # Read once when the definition was handed over; otherwise lazily, so the
    # file the *candidate* changed is the file the run sends.
    cached = definition

    # The key's first component. Passed explicitly by `aef migrate`, which
    # knows the persona's name at generation time, rather than read from the
    # file: the executor computes the key BEFORE the node body runs, and a key
    # function that has to open a file can fail in a place with no useful
    # error path. Falls back to the definition's name, then to the file path.
    key_name = agent_name or (cached.name if cached is not None else "") or agent_file or node_id

    def _definition() -> PromptAgentDefinition:
        if cached is not None:
            return cached
        path = resolve_agent_file(agent_file, module_file)
        return load_agent_file(path, source=agent_file)

    def prompt_agent_fn(
        state: AEFState, ctx: Context, services: Services
    ) -> tuple[StateDelta, Route]:
        agent = _definition()
        result = services.require_model_provider().complete(
            CompletionRequest(
                messages=(
                    ProviderMessage(role="system", content=agent.body),
                    ProviderMessage(role="user", content=state.objective),
                ),
                model="",
            )
        )
        provenance = Provenance(
            node_id=ctx.node_id,
            graph_version=ctx.graph_version,
            model=result.model or None,
            ts=ctx.now,
            trace_id=ctx.trace_id,
            token_cost=result.input_tokens + result.output_tokens,
        )
        return (
            StateDelta(
                working_memory={node_id: result.content.strip()},
                plan=Plan(goal=state.objective, status="done"),
                provenance=[provenance],
            ),
            route,
        )

    def key_fn(state: AEFState) -> str:
        return prompt_agent_idempotency_key(key_name, state.objective)

    return Node(
        id=node_id,
        version=version,
        fn=prompt_agent_fn,
        # Calls a model. Declaring True would make `ReplayEngine` re-execute
        # it and assert the reply matched, which no model guarantees.
        deterministic=False,
        side_effects=SideEffect.EXTERNAL_CALL,
        idempotency_key_fn=key_fn,
    )
