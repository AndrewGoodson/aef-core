"""Do the five things an adopter must supply actually exist?

Each obligation was discovered by an adopter (or by me, in this repo) being
stuck, one command at a time, in the worst possible order: run the loop, get
a refusal, fix one thing, get the next refusal. This reports all five at once
with the command that fixes each.

`bless` lives here too, because LOOP.md obligation 5 told owners to archive a
blessed baseline and **no command existed to do it** — the obligation was
literally unmeetable and G5 refused every candidate forever (ADR 0073).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aef.harness import archive, ledger
from aef.harness.corpus import Expected, load_corpus


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

    def render(self) -> str:
        width = max(len(o.name) for o in self.obligations)
        lines = ["Loop readiness — five things you must supply", ""]
        for o in self.obligations:
            lines.append(f"  [{'OK' if o.met else '--'}] {o.name:<{width}}  {o.detail}")
            if not o.met:
                lines.append(f"       fix: {o.fix}")
        lines.append("")
        lines.append(
            "All five green — the loop can gate a candidate on real evidence."
            if self.ready
            else "Until every line is OK the gates refuse for lack of evidence, which is "
            "correct behaviour and not a bug."
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
                    "aef loop record <module> --corpus corpus --scenario-id <id> "
                    "--objective '...' , then label one MUST_FAIL. Without a tripwire "
                    "the gates cannot detect reward hacking (ADR 0060)."
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

    return Preflight(obligations=tuple(checks))


def bless(
    *,
    repo_root: Path,
    state_root: Path,
    agent_path: str,
    graph_id: str,
    at: datetime,
    note: str = "",
) -> archive.ArchiveEntry:
    """Archive the current Zone A state as the owner-blessed baseline.

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

    source = repo_root / agent_path
    if not source.is_file():
        raise BlessError(f"no agent source at {source}; nothing to bless")

    entry = archive.record(
        state_root / "archive",
        graph_id,
        files={agent_path: source.read_bytes()},
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
