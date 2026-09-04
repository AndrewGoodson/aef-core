"""Do the things an adopter must supply actually exist?

Each obligation was discovered by an adopter (or by me, in this repo) being
stuck, one command at a time, in the worst possible order: run the loop, get
a refusal, fix one thing, get the next refusal. This reports all of them at
once with the command that fixes each.

`bless` lives here too, because LOOP.md obligation 5 told owners to archive a
blessed baseline and **no command existed to do it** — the obligation was
literally unmeetable and G5 refused every candidate forever (ADR 0073).

The sixth obligation, *model calls visible*, was added by ADR 0137 and is the
only one an adopter cannot discover by being stuck: a node that constructs its
own vendor client works perfectly, `aef doctor` reports green, and the failure
arrives much later as a gate that either makes live calls or scores the
candidate 0 — because the call was invisible to the recorder, so the scenario
carries no cassette to replay.

**These obligations are ADVISORY, and this file used to say otherwise.** Only
`aef loop doctor` reads `Preflight.ready`; `cycle`, `gate` and `run` never
have. ADR 0137 §2 claimed "`Preflight.ready` is false while it stands, so the
gates refuse", and `render()` closed with "the gates refuse for lack of
evidence" — both false, and reproduced: `loop doctor` exits 1 with obligation
6 red and `loop cycle` then proposes and gates the same repo. What is true is
narrower and is now what the text says: obligations 1, 2 and 5 are enforced
later by the gates themselves (G2/G3 refuse an empty corpus, G5 refuses
without a blessed baseline, a graph nothing routes to reflect records no
failure memory so the proposer never proposes), while 3, 4 and 6 are not
enforced anywhere and the loop will run without them. `cmd_cycle`/`cmd_gate`
print the unmet ones so the surface stops saying nothing. See ADR 0141 for
why they were not made blocking.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aef.harness import archive, ledger
from aef.harness.corpus import Expected, load_corpus
from aef.harness.git import GitRepo
from aef.harness.vendor_scan import MODEL_SDK_ROOTS, VendorImport, scan_file
from aef.harness.zones import DEFAULT_AGENT_ROOT


class BlessError(RuntimeError):
    pass


@dataclass(frozen=True)
class Obligation:
    name: str
    met: bool
    detail: str
    fix: str


@dataclass(frozen=True)
class Preflight:
    obligations: tuple[Obligation, ...]

    @property
    def ready(self) -> bool:
        return all(o.met for o in self.obligations)

    @property
    def unmet(self) -> tuple[Obligation, ...]:
        return tuple(o for o in self.obligations if not o.met)

    def render(self) -> str:
        width = max(len(o.name) for o in self.obligations)
        count = len(self.obligations)
        lines = [f"Loop readiness — {count} things you must supply", ""]
        for o in self.obligations:
            lines.append(f"  [{'OK' if o.met else '--'}] {o.name:<{width}}  {o.detail}")
            if not o.met:
                lines.append(f"       fix: {o.fix}")
        lines.append("")
        # This used to close with "the gates refuse for lack of evidence,
        # which is correct behaviour and not a bug." Nothing but this command
        # reads `ready`, so that sentence described a control that does not
        # exist: `loop doctor` exits 1 and `loop cycle` then gates the same
        # repo anyway (ADR 0141). Say what is true instead.
        lines.append(
            f"All {count} green — the loop can gate a candidate on real evidence."
            if self.ready
            else "These are ADVISORY and this command is the only thing that reads them: "
            "`aef loop cycle` and `aef loop gate` will still run, and will print the "
            "unmet ones. Some enforce themselves later — G2/G3 refuse an empty corpus "
            "and G5 refuses without a blessed baseline — but a missing halt channel or "
            "an invisible model call stops nothing, which is why they are listed here."
        )
        return "\n".join(lines)


def _reflect_is_routed_to(agent_source: Path) -> tuple[bool, str]:
    """A reflect node must exist AND a node must ROUTE to it.

    Checking only that the node exists is not enough, and this is the trap
    that has now caught two people: an `Edge` to a reflect node does not wire
    it. Routing is chosen by node code, so a work node returning `END` never
    reaches reflect however the edges are drawn (ADR 0070).
    """
    if not agent_source.is_file():
        return False, f"no agent source at {agent_source}"
    source = agent_source.read_text()
    if "make_reflect_node" not in source:
        return False, "no reflect node in the graph"

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"agent source does not parse: {exc}"

    # Find the id the reflect node is constructed with, defaulting to the
    # factory's own default.
    reflect_id = "reflect"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "make_reflect_node"
        ):
            for kw in node.keywords:
                if kw.arg == "node_id" and isinstance(kw.value, ast.Constant):
                    reflect_id = str(kw.value.value)

    # Only Return statements inside NODE functions count. Scanning every
    # return in the module false-positived on `Edge(to_node="reflect")` inside
    # build_graph's return — the detector passed the exact trap it exists to
    # catch, and only a planted-fault test revealed it.
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = [a.arg for a in fn.args.args]
        if len(args) != 3:
            continue  # not (state, ctx, services)
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and node.value is not None:
                for literal in ast.walk(node.value):
                    if isinstance(literal, ast.Constant) and literal.value == reflect_id:
                        return True, f"{fn.name}() returns {reflect_id!r} as its Route"

    return (
        False,
        "a reflect node exists but nothing routes to it — an Edge does not wire it",
    )


def _module_candidates(repo_root: Path, dotted: str) -> list[Path]:
    """Where an absolute `import a.b.c` could live inside this repo.

    Repo-root-relative, because that is where `aef run <module>` and the node
    body `aef migrate` generates (`from src.my_agent import run_agent`) both
    resolve from: the adopter's repo root is on `sys.path`. `a.b` is also
    tried as `a/b.py` when written `from a import b`, since that form names a
    module as often as it names a symbol.
    """
    parts = dotted.split(".")
    return [
        repo_root.joinpath(*parts).with_suffix(".py"),
        repo_root.joinpath(*parts, "__init__.py"),
    ]


def _reachable_modules(repo_root: Path, entry: Path) -> list[Path]:
    """Every in-repo `.py` file the entry file reaches by import, transitively.

    Only files that resolve inside `repo_root` are followed. A third-party
    import is not the adopter's code and is not this obligation's business —
    `anthropic` itself is expected to import `anthropic`.

    Bounded by the visited set; a circular import terminates.
    """
    entry = entry.resolve()
    seen: set[Path] = {entry}
    queue: list[Path] = [entry]
    order: list[Path] = [entry]

    while queue:
        current = queue.pop()
        try:
            tree = ast.parse(current.read_text(encoding="utf-8"), filename=str(current))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        dotted_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                dotted_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                dotted_names.append(node.module)
                # `from a.b import c` — `c` may itself be a module.
                dotted_names.extend(f"{node.module}.{a.name}" for a in node.names)
        for dotted in dotted_names:
            for candidate in _module_candidates(repo_root, dotted):
                resolved = candidate.resolve()
                if resolved in seen or not candidate.is_file():
                    continue
                seen.add(resolved)
                order.append(resolved)
                queue.append(resolved)
    return order


_UNROUTED_MARKER = "UNROUTED wrapper for `"
_NOT_ROUTED_MARKER = "Not routed because "


def _migrate_refusals(entry: Path) -> dict[str, str]:
    """`{dotted module: why migrate refused to route it}`, read from the graph.

    `aef migrate` writes the decision into every generated node's own
    docstring — `UNROUTED wrapper for \\`src.my_agent.run_agent\\`` followed by
    `Not routed because <reason>`. Parsing that back is how this file tells
    "migrate has not looked at this yet" from "migrate looked and refused",
    which are the two cases whose remedies are completely different.

    Read from the docstring rather than by importing `aef.cli.migrate`: the
    harness does not import the CLI, and the generated file is the artefact
    the adopter actually has in front of them.
    """
    try:
        tree = ast.parse(entry.read_text(encoding="utf-8"), filename=str(entry))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}
    refusals: dict[str, str] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(fn) or ""
        if not doc.startswith(_UNROUTED_MARKER):
            continue
        dotted = doc[len(_UNROUTED_MARKER) :].split("`", 1)[0]
        module = dotted.rsplit(".", 1)[0] if "." in dotted else dotted
        _, _, tail = doc.partition(_NOT_ROUTED_MARKER)
        reason = " ".join(tail.split("\n\n", 1)[0].split()).rstrip(".")
        refusals[module] = reason
    return refusals


def _dotted_from(repo_root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(repo_root.resolve())
    except ValueError:  # pragma: no cover - reachability keeps them inside the repo
        return path.stem
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


_GENERIC_FIX = (
    "run `aef migrate --dir . --force` and READ ITS REPORT. Where it can, it rewrites the "
    "node to call `services.require_model_provider().complete(...)` instead of a client the "
    "node builds itself. Where it cannot it prints `NOT routed because ...` and generates a "
    "wrapper that leaves this obligation red — re-running it then changes nothing, and the "
    "remedy becomes the hand-routing one this message will name once migrate has said so."
)


def _hand_routing_fix(module: str, reason: str) -> str:
    return (
        f"`aef migrate --dir . --force` will NOT fix this and will loop: it already refused to "
        f"route {module} ({reason}), and regenerating produces the same unrouted wrapper. Two "
        f"edits, both yours. (1) Rewrite that node's body to call "
        f"`services.require_model_provider().complete(...)` instead of calling your function, "
        f"re-expressing whatever the refusal reason names. (2) DELETE the "
        f"`from {module} import ...` line from the node — {module} stays in the graph's "
        f"reachable set while that import stands, so the obligation stays red even after the "
        f"body is routed. Neither step is optional and neither is automatic."
    )


def model_calls_are_visible(repo_root: Path, agent_path: str) -> tuple[bool, str, str]:
    """`(visible, detail, fix)` — no module reachable from the graph may import
    a **model** SDK.

    This is constraint #3 pointed at the adopter instead of at this repo. The
    scanner is the one `tests/test_vendor_isolation.py` has run since Phase 0
    (`aef/harness/vendor_scan.py`); the difference is where it is aimed and
    **which list it is aimed with**.

    `MODEL_SDK_ROOTS`, not `VENDOR_TOP_LEVEL_MODULES`. The first version of
    this function inherited `scan_file`'s constraint-#3 default, so an adopter
    whose graph reached a module doing `import psycopg2` was permanently
    blocked and told to route their Postgres connection through
    `require_model_provider().complete(...)`. Fourteen of the nineteen names
    in the constraint #3 list are not model SDKs; ADR 0137's "it over-reports
    nothing" was false for all fourteen (ADR 0141). Constraint #3 still uses
    the full list where it belongs — inside this repo, in
    `tests/test_vendor_isolation.py`.

    A node that builds its own client is not a style problem. It bypasses the
    policy engine, the fallback chain and the harness login, and — the part
    that costs the adopter a whole loop — it is invisible to
    `aef/harness/recorder.py`, so its scenario carries **no** `RecordedCall`.
    Replay with `on_miss="fail"` then has nothing to serve and nothing to
    refuse: the node reaches the vendor live, or fails for want of a
    credential and scores 0. Both were reproduced (ADR 0137).
    """
    entry = (repo_root / agent_path).resolve()
    if not entry.is_file():
        return (
            False,
            f"no agent source at {entry} — nothing to scan",
            f"point --agent-path at the module that builds your graph; {agent_path!r} is "
            f"not a file under {repo_root}",
        )

    modules = _reachable_modules(repo_root, entry)
    found: list[VendorImport] = []
    for module in modules:
        found.extend(scan_file(module, roots=MODEL_SDK_ROOTS))
    if not found:
        return (
            True,
            f"{len(modules)} reachable module(s), none imports a model SDK",
            "",
        )

    first = found[0]
    try:
        where = first.path.relative_to(repo_root.resolve())
    except ValueError:  # pragma: no cover - reachability keeps them inside the repo
        where = first.path
    extra = f" (+{len(found) - 1} more)" if len(found) > 1 else ""
    detail = f"{where}:{first.lineno} imports {first.module}{extra} — the harness cannot see it"

    # WHICH fix, and this is the whole point of ADR 0141's R4. Telling an
    # adopter to re-run migrate when migrate has already refused this exact
    # function is a loop: the same wrapper is regenerated and the obligation
    # is red again, with the same message.
    refusals = _migrate_refusals(entry)
    dotted = _dotted_from(repo_root, first.path)
    reason = refusals.get(dotted)
    consequence = (
        " A node with its own client bypasses the policy engine and the fallback chain, "
        "and the recorder captures no RecordedCall for it — so the gates replay nothing "
        "and either call the vendor live or score it 0."
    )
    fix = _hand_routing_fix(dotted, reason) if reason is not None else _GENERIC_FIX
    return False, detail, fix + consequence


def preflight(
    *,
    repo_root: Path,
    state_root: Path,
    corpus_root: Path,
    agent_path: str,
    graph_id: str,
    halt_channel_configured: bool,
    observations: Path,
) -> Preflight:
    checks: list[Obligation] = []

    # 1 — corpus with at least one tripwire
    try:
        corpus = load_corpus(corpus_root) if corpus_root.is_dir() else None
        scenarios = corpus.scenarios if corpus else ()
        tripwires = [s for s in scenarios if s.expected is Expected.MUST_FAIL]
        checks.append(
            Obligation(
                name="corpus + tripwire",
                met=bool(scenarios) and bool(tripwires),
                detail=f"{len(scenarios)} scenario(s), {len(tripwires)} tripwire(s)",
                fix=(
                    "aef loop record <module> --corpus corpus --scenario-id tripwire-1 "
                    "--objective '<a task beyond this agent>' --split validation "
                    "--expected must_fail --working-memory '{\"difficulty\": 99}'. "
                    "Without a tripwire the gates cannot detect reward hacking (ADR 0060)."
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 - a broken corpus is an unmet obligation
        checks.append(
            Obligation("corpus + tripwire", False, f"corpus unreadable: {exc}", "fix the corpus")
        )

    # 2 — a reflect node something routes to
    routed, why = _reflect_is_routed_to(repo_root / agent_path)
    checks.append(
        Obligation(
            name="reflect node routed to",
            met=routed,
            detail=why,
            fix=(
                "add make_reflect_node() to your graph AND make a node "
                "`return delta, 'reflect'` — an Edge alone does not route (ADR 0070)"
            ),
        )
    )

    # 3 — observations
    count = len(observations.read_text().splitlines()) if observations.is_file() else 0
    checks.append(
        Obligation(
            name="observations",
            met=count > 0,
            detail=f"{count} recorded run(s) at {observations}",
            fix="pass --observations from your production runs, then "
            "`aef loop monitor --observations <path>`",
        )
    )

    # 4 — halt channel
    checks.append(
        Obligation(
            name="halt channel",
            met=halt_channel_configured,
            detail="configured" if halt_channel_configured else "none — a halt would tell nobody",
            fix="set AEF_HALT_WEBHOOK in your environment (never in this repo)",
        )
    )

    # 5 — blessed baseline
    versions = archive.versions(state_root / "archive", graph_id)
    checks.append(
        Obligation(
            name="blessed baseline",
            met=bool(versions),
            detail=f"{len(versions)} archived version(s)",
            fix=f"aef loop bless --repo . --state {state_root} --agent-path {agent_path}",
        )
    )

    # 6 — every model call reaches the harness (ADR 0137, corrected by 0141)
    visible, detail, fix = model_calls_are_visible(repo_root, agent_path)
    checks.append(Obligation(name="model calls visible", met=visible, detail=detail, fix=fix))

    return Preflight(obligations=tuple(checks))


def _zone_a_files(repo: GitRepo, ref: str, agent_root: str) -> dict[str, bytes]:
    """Every file under the Zone A root **as of `ref`**, keyed by repo path.

    Read from git, not from the working tree, for two reasons. It is the same
    source `_candidate_files` reads, so G5's two inputs describe the same tree
    the same way — reading one side from disk let untracked build output
    (a `__pycache__` the candidate had committed, in the run that found this)
    appear on one side only and charged 0.430 drift for a two-line change.
    And a baseline blessed from a dirty working tree records a state that
    exists nowhere in history, so nothing could ever be compared against it
    reproducibly (ADR 0074).
    """
    paths = repo.list_tree(ref, agent_root)
    return {p: repo.run_bytes("show", f"{ref}:{p}") for p in sorted(paths)}


def bless(
    *,
    repo_root: Path,
    state_root: Path,
    agent_path: str,
    graph_id: str,
    at: datetime,
    note: str = "",
    agent_root: str = DEFAULT_AGENT_ROOT,
    ref: str = "HEAD",
) -> archive.ArchiveEntry:
    """Archive the current Zone A state as the owner-blessed baseline.

    **The whole Zone A tree, not one file.** G5 measures drift as
    `structural_drift(baseline, candidate)`, which unions the two key sets;
    archiving a single file while the candidate side describes the whole tree
    made every other Zone A file read as deleted, and the *first* candidate
    after a blessing was rejected for drift it had not caused (ADR 0074).
    Baseline and candidate must describe the same tree or the metric is
    measuring the difference between two questions.

    Refuses when one already exists. Rebaselining is owner-only and
    rate-limited by G5 (ADR 0053), and a `bless` that silently replaced the
    baseline would route around that — the drift budget is measured against
    this, so overwriting it resets drift to zero without anyone deciding to.
    """
    existing = archive.versions(state_root / "archive", graph_id)
    if existing:
        raise BlessError(
            f"graph {graph_id!r} already has {len(existing)} archived version(s); a baseline "
            f"exists. Rebaselining is a separate, rate-limited owner decision (G5, ADR 0053) "
            f"— blessing again here would reset the drift budget without anyone choosing to."
        )

    repo = GitRepo(root=repo_root)
    if not repo.path_exists_at(ref, agent_path):
        raise BlessError(
            f"no agent source at {agent_path} in {ref}; nothing to bless. If you have just "
            f"written it, commit it first — the baseline is read from git so that what was "
            f"blessed is a state the gates can actually compare against."
        )

    files = _zone_a_files(repo, ref, agent_root)
    if not files:  # pragma: no cover - agent_path is inside agent_root in practice
        raise BlessError(f"no files under {agent_root!r} at {ref}; nothing to bless")

    entry = archive.record(
        state_root / "archive",
        graph_id,
        files=files,
        base_sha="0" * 40,
        head_sha="0" * 40,
        recorded_at=at,
        notes=note or "owner-blessed baseline",
    )
    ledger.append(
        state_root,
        kind=ledger.EventKind.BLESSED,
        at=at,
        proposal_id=f"baseline@{graph_id}",
        summary="owner-blessed baseline archived",
        detail={"archive_version": entry.version, "blessed": True},
    )
    return entry
