"""`aef loop` — the CLI surface over the self-rewiring driver.

Two boundary decisions live here rather than deeper in the harness.

**Network-isolation attestation is a CLI flag**, not something `sandbox.py`
reads from the environment. The value has to come from Zone B configuration
(the CI workflow), and an env read inside the sandbox would put a
security-relevant input somewhere closer to the candidate.

**A halted loop exits 2, distinct from a rejection's 1.** "Stop, something is
wrong with the system" and "this candidate is no good" are different
outcomes, and a workflow that cannot tell them apart will retry the first.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from aef.harness.corpus import Expected, Split, load_corpus
from aef.harness.git import GitRepo
from aef.harness.loop import (
    EXIT_HALTED,
    EXIT_OK,
    EXIT_REJECTED,
    LoopConfig,
    LoopPaths,
    PolicyConfigError,
    default_digest_window,
)
from aef.harness.loop import digest as loop_digest
from aef.harness.loop import gate as loop_gate
from aef.harness.loop import monitor as loop_monitor
from aef.harness.loop import status as loop_status
from aef.harness.monitoring import LoopHaltedError
from aef.harness.recorder import record_to_corpus
from aef.harness.zones import DEFAULT_AGENT_ROOT, ZonePolicy


def _build_commands(args: argparse.Namespace) -> tuple[tuple[str, ...], ...] | None:
    """Repo-specific build commands, or None to take G1's default.

    Each `--build-command` is a whole shell-free command, split on spaces.
    Repeatable, because a green bar is usually more than one command.
    """
    raw = getattr(args, "build_command", None)
    if not raw:
        return None
    return tuple(tuple(c.split()) for c in raw)


def _config(args: argparse.Namespace) -> LoopConfig:
    corpus_dir = Path(args.corpus) if getattr(args, "corpus", None) else None
    return LoopConfig(
        repo=GitRepo(root=Path(args.repo)),
        paths=LoopPaths(root=Path(args.state)),
        base_ref=getattr(args, "base", "main"),
        graph_id=args.graph_id,
        corpus=load_corpus(corpus_dir) if corpus_dir and corpus_dir.is_dir() else None,
        network_isolated=bool(getattr(args, "network_isolated", False)),
        build_commands=_build_commands(args),
        entrypoint=getattr(args, "entrypoint", None),
        config_path=getattr(args, "config", None),
        # Both sides of G5's drift metric must describe the SAME tree.
        # `bless` took an agent_root and `_config` never set a zone_policy,
        # so a non-default root gave the baseline and the candidate two
        # different trees — the ADR 0074 defect, latent (ADR 0084).
        zone_policy=ZonePolicy(agent_root=getattr(args, "agent_root", DEFAULT_AGENT_ROOT)),
        # Never wired to a flag. Enabling Tier-1 auto-merge is an owner
        # action against the source, not something a CI invocation can do by
        # passing an argument (ADR 0045).
        tier1_enabled=False,
    )


def cmd_gate(args: argparse.Namespace) -> int:
    config = _config(args)
    try:
        run = loop_gate(
            config,
            args.head,
            now=datetime.now(UTC),
            workdir=Path(args.workdir),
        )
    except PolicyConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED

    print(run.report)
    if run.halted:
        print("\nLOOP HALTED — a proposal reached for the harness. Read the ledger.")
    return run.exit_code


def cmd_monitor(args: argparse.Namespace) -> int:
    config = _config(args)
    # A deployment writes observations wherever it runs; the monitor reads
    # <state>/observations.jsonl. Nothing connected the two, so every window
    # reported unobserved and silently reverted (ADR 0072).
    if args.observations:
        source = Path(args.observations)
        if not source.is_file():
            print(f"error: no observations file at {source}", file=sys.stderr)
            return EXIT_REJECTED
        target = config.paths.observations
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            target.write_text(source.read_text())

    try:
        run = loop_monitor(config, now=datetime.now(UTC))
    except PolicyConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED

    print(f"checked {run.checked} merged change(s)")
    for line in run.lines:
        print(f"  {line}")
    for proposal_id in run.rolled_back:
        print(f"  ROLLED BACK: {proposal_id}")
    if run.halted:
        print("\nLOOP HALTED:")
        for reason in run.halt_reasons:
            print(f"  - {reason}")
    return run.exit_code


def cmd_digest(args: argparse.Namespace) -> int:
    config = _config(args)
    since, until = default_digest_window(datetime.now(UTC))
    from aef.harness.harvest import load_runs

    notifier = _halt_notifier()
    result = loop_digest(
        config,
        since=since,
        until=until,
        owner_edits=args.owner_edits,
        halt_channel_configured=bool(getattr(notifier, "configured", False)),
        runs_recorded=len(load_runs(Path(args.runs))) if args.runs else 0,
    )
    print(result.to_json() if args.json else result.render())
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    status = loop_status(config)
    print(status.render())
    # A broken ledger or an engaged kill switch is not a healthy system, and
    # `status` is often the thing a workflow keys off.
    return EXIT_HALTED if (status.halted or not status.ledger_ok) else EXIT_OK


def cmd_record(args: argparse.Namespace) -> int:
    from aef.cli.run import load_graph_module

    graph = load_graph_module(args.module)
    from aef.kernel import Services
    from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
    from aef.security.tool import PolicyEngine
    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.state import AEFState

    recorded = record_to_corpus(
        Path(args.corpus),
        graph,
        AEFState(
            run_id=args.scenario_id,
            agent_id=args.agent_id,
            objective=args.objective,
            # Without this the recorder could only ever run the agent with an
            # empty working memory — so every recorded scenario landed on the
            # agent's happy path, and the failing cases LOOP.md tells owners to
            # record (and every tripwire) were unreachable from the CLI that
            # records them (ADR 0074).
            working_memory=json.loads(args.working_memory) if args.working_memory else {},
        ),
        # Same wiring as `aef run`: an agent following obligation 2 has a
        # reflect node, and a bare Services() cannot run one. Recording is
        # useless if it cannot record the agent the adopter was told to build
        # (ADR 0073).
        Services(
            memory=InMemoryMemoryStore(),
            critic=RuleBasedCritic(),
            judge=RuleBasedJudge(rubric={"quality": 1.0}),
            # Deny-by-default. Without it an agent whose tool calls go through
            # `aef.security.tool.Tool` — which the generated CLAUDE.md instructs —
            # dies with ServiceNotConfiguredError (ADR 0079).
            policy_engine=PolicyEngine(),
        ),
        scenario_id=args.scenario_id,
        split=Split(args.split),
        recorded_at=datetime.now(UTC),
        notes=args.notes,
        allow_holdout=args.i_am_spending_the_holdout,
        expected=Expected(args.expected),
    )
    print(f"recorded {recorded.scenario.id} ({recorded.scenario.split.value}) -> {recorded.path}")
    print(f"  {len(recorded.scenario.trace)} node execution(s) pinned")
    return EXIT_OK


def cmd_harvest(args: argparse.Namespace) -> int:
    from aef.cli.run import load_graph_module
    from aef.harness.harvest import harvest

    # Harvest writes to corpus/, which IS the evidence every behavioural gate
    # is measured against. A halted loop must not have its gate evidence
    # changed underneath it (ADR 0069).
    config = _config(args)
    try:
        config.paths.kill_switch.check()
    except PolicyConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED

    outcome = harvest(
        Path(args.runs),
        Path(args.corpus),
        load_graph_module(args.module),
        now=datetime.now(UTC),
        include_successes=args.include_successes,
        daily_limit=args.daily_limit,
    )
    for line in outcome.lines:
        print(line)
    return EXIT_OK


def _halt_notifier() -> object:
    """Read the halt webhook from the environment, at the CLI boundary.

    Never read inside the harness: the URL is owner configuration that lives
    outside this repository, and a module that reaches for the environment
    itself is one the candidate is closer to influencing.
    """
    import os

    from aef.harness.monitoring import HaltNotifier

    return HaltNotifier(webhook_url=os.environ.get("AEF_HALT_WEBHOOK") or None)


def cmd_cycle(args: argparse.Namespace) -> int:
    from aef.cli.run import load_graph_module
    from aef.harness.loop import cycle as loop_cycle
    from aef.harness.memory_store import FileMemoryStore

    config = _config(args)
    graph = load_graph_module(args.module) if args.module else None
    try:
        run = loop_cycle(
            config,
            now=datetime.now(UTC),
            workdir=Path(args.workdir),
            runs_dir=Path(args.runs) if args.runs else None,
            corpus_root=Path(args.corpus) if args.corpus else None,
            graph=graph,
            # Durable, not in-process: a store constructed here would be
            # empty every invocation and the proposer would never see a
            # recorded failure (ADR 0069).
            # `Path(None)` raises TypeError, which main() catches and turns
            # into exit 1 — the code that means "this candidate is no good".
            # A missing flag is a configuration error and must not be
            # reported as a verdict on a candidate, or CI retries it forever
            # (ADR 0075). None reaches the driver's own explicit refusal.
            memory=FileMemoryStore(path=Path(args.memory)) if args.memory else None,
            agent_path=args.agent_path,
        )
    except PolicyConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED

    for line in run.lines:
        print(f"  {line}")
    return run.exit_code


def cmd_bless(args: argparse.Namespace) -> int:
    from aef.harness.preflight import BlessError, bless

    config = _config(args)
    try:
        config.paths.kill_switch.check()
    except PolicyConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED
    try:
        entry = bless(
            repo_root=Path(args.repo),
            state_root=config.paths.root,
            agent_path=args.agent_path,
            agent_root=args.agent_root,
            graph_id=args.graph_id,
            at=datetime.now(UTC),
            note=args.note,
        )
    except BlessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    print(f"blessed {args.agent_path} as baseline v{entry.version} for graph {args.graph_id!r}")
    print("  G5 now has a reference point to measure drift against.")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from aef.harness.preflight import preflight

    config = _config(args)
    result = preflight(
        repo_root=Path(args.repo),
        state_root=config.paths.root,
        corpus_root=Path(args.corpus),
        agent_path=args.agent_path,
        graph_id=args.graph_id,
        halt_channel_configured=bool(getattr(_halt_notifier(), "configured", False)),
        observations=Path(args.observations) if args.observations else config.paths.observations,
    )
    print(result.render())
    return EXIT_OK if result.ready else EXIT_REJECTED


def add_loop_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("loop", help="drive the self-rewiring loop (gate/monitor/digest)")
    loop_subs = p.add_subparsers(dest="loop_command", required=True)

    def _common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--repo", default=".", help="git repository root")
        sub.add_argument(
            "--state", required=True, help="loop state dir (ledger, archive, kill switch)"
        )
        sub.add_argument("--graph-id", default="default")
        sub.add_argument(
            "--agent-root",
            default=DEFAULT_AGENT_ROOT,
            help=(
                "the Zone A root — the only directory the loop may propose changes to. "
                "Both sides of G5's drift metric are read from it, so `bless` and the "
                "gate must be given the same value or they describe different trees."
            ),
        )

    p_gate = loop_subs.add_parser("gate", help="evaluate one candidate branch")
    _common(p_gate)
    p_gate.add_argument("--base", default="main")
    p_gate.add_argument("--head", required=True)
    p_gate.add_argument("--workdir", required=True, help="scratch dir for gate execution")
    p_gate.add_argument("--corpus", default=None)
    p_gate.add_argument(
        "--config",
        default=None,
        help=(
            "path to aef.yaml, whose `policies` and `tools.allow` become the policy "
            "engine the corpus runs under. READ FROM THE BASE REF, never from the "
            "candidate — otherwise a candidate could widen the rules it is judged by."
        ),
    )
    p_gate.add_argument(
        "--entrypoint",
        default=None,
        help=(
            "module:factory that builds your graph, e.g. agents.mine.graph:build_graph. "
            "G2 and G3 refuse without it — they have to execute the corpus to have anything "
            "to say. There is deliberately no default: one would name a layout your repo "
            "may not have and fail as an import error inside a gate rejection."
        ),
    )
    p_gate.add_argument(
        "--network-isolated",
        action="store_true",
        help="attest that the caller (a CI container) provides network isolation. "
        "A process cannot revoke its own network access; passing this without real "
        "isolation makes the sandbox's report untrue.",
    )
    p_gate.add_argument(
        "--build-command",
        action="append",
        default=None,
        help="a command G1 must pass, e.g. 'python -m pytest -q'. Repeatable. "
        "Defaults to pytest only — anything more is repo-specific.",
    )
    p_gate.set_defaults(handler=cmd_gate)

    p_monitor = loop_subs.add_parser("monitor", help="evaluate post-merge windows, auto-rollback")
    _common(p_monitor)
    p_monitor.add_argument(
        "--observations",
        default=None,
        help="the observations JSONL your deployment wrote. Without it the monitor sees "
        "no live runs and every window reverts for lack of evidence.",
    )
    p_monitor.set_defaults(handler=cmd_monitor)

    p_digest = loop_subs.add_parser("digest", help="weekly trend report")
    _common(p_digest)
    p_digest.add_argument("--json", action="store_true")
    p_digest.add_argument("--owner-edits", type=int, default=0)
    p_digest.add_argument("--runs", default=None, help="runs dir, to report whether any exist")
    p_digest.set_defaults(handler=cmd_digest)

    p_status = loop_subs.add_parser("status", help="kill switch, ledger integrity, open windows")
    _common(p_status)
    p_status.set_defaults(handler=cmd_status)

    p_record = loop_subs.add_parser("record", help="promote a real run into a corpus scenario")
    p_record.add_argument("module", help="importable module exposing build_graph()")
    p_record.add_argument("--corpus", required=True)
    p_record.add_argument("--scenario-id", required=True)
    p_record.add_argument("--objective", required=True)
    p_record.add_argument("--agent-id", default="recorder")
    p_record.add_argument("--split", default="train", choices=[s.value for s in Split])
    p_record.add_argument(
        "--expected",
        default=Expected.UNSPECIFIED.value,
        choices=[e.value for e in Expected],
        help=(
            "the OWNER's claim about this task, which no recording can supply. "
            "must_fail makes the scenario a TRIPWIRE: a task genuinely beyond the agent's "
            "remit, where claiming success is a lie rather than an improvement. Without at "
            "least one, the gates cannot detect reward hacking (ADR 0060)."
        ),
    )
    p_record.add_argument("--notes", default="")
    p_record.add_argument(
        "--working-memory",
        default=None,
        help=(
            "JSON object seeding AEFState.working_memory, e.g. '{\"difficulty\": 99}'. "
            "This is how you drive the agent into the FAILING cases worth recording — a "
            "corpus where everything already passes cannot demonstrate an improvement, and "
            "a tripwire has to be a task the agent genuinely cannot do."
        ),
    )
    p_record.add_argument(
        "--i-am-spending-the-holdout",
        action="store_true",
        help="required to write to the holdout split. It is the owner's only independent "
        "read of whether the loop improves anything; filling it casually destroys that "
        "independence silently.",
    )
    p_record.set_defaults(handler=cmd_record)

    p_harvest = loop_subs.add_parser(
        "harvest", help="promote recorded production runs into corpus scenarios"
    )
    _common(p_harvest)
    p_harvest.add_argument("module", help="importable module exposing build_graph()")
    p_harvest.add_argument("--runs", required=True, help="dir of runs from `aef run --record-runs`")
    p_harvest.add_argument("--corpus", required=True)
    p_harvest.add_argument(
        "--daily-limit",
        type=int,
        default=5,
        help="cap promotions per day. One bad deploy can produce thousands of failing "
        "runs; without a cap the corpus fills with a single incident and the gates "
        "start measuring that incident instead of the agent.",
    )
    p_harvest.add_argument(
        "--include-successes",
        action="store_true",
        help="also promote runs that passed. Off by default: failures carry the "
        "information, and auto-promoting successes inflates the pass rate the gates "
        "measure against.",
    )
    p_harvest.set_defaults(handler=cmd_harvest)

    p_cycle = loop_subs.add_parser(
        "cycle", help="one turn of the loop: harvest -> propose -> gate -> record"
    )
    _common(p_cycle)
    p_cycle.add_argument("--base", default="main")
    p_cycle.add_argument("--workdir", required=True)
    p_cycle.add_argument("--module", default=None, help="module exposing build_graph()")
    p_cycle.add_argument("--runs", default=None, help="dir from `aef run --record-runs`")
    p_cycle.add_argument("--corpus", default=None)
    p_cycle.add_argument(
        "--config",
        default=None,
        help=(
            "path to aef.yaml, whose `policies` and `tools.allow` become the policy "
            "engine the corpus runs under. READ FROM THE BASE REF, never from the "
            "candidate — otherwise a candidate could widen the rules it is judged by."
        ),
    )
    p_cycle.add_argument(
        "--entrypoint",
        default=None,
        help="module:factory that builds your graph; G2/G3 refuse without it",
    )
    p_cycle.add_argument("--agent-path", default="agents/demo/graph.py")
    p_cycle.add_argument(
        "--memory",
        default=None,
        help="path to the durable memory JSONL the reflect node writes. Without it the "
        "proposer has no recorded failures to ground in and will never propose.",
    )
    p_cycle.add_argument(
        "--build-command",
        action="append",
        default=None,
        help="a command G1 must pass, e.g. 'python -m pytest -q'. Repeatable. "
        "Defaults to pytest only — anything more is repo-specific.",
    )
    p_cycle.set_defaults(handler=cmd_cycle)

    p_bless = loop_subs.add_parser(
        "bless", help="archive the current Zone A state as the owner-blessed baseline"
    )
    _common(p_bless)
    p_bless.add_argument("--agent-path", default="agents/demo/graph.py")
    p_bless.add_argument("--note", default="", help="why this state is the baseline")
    p_bless.set_defaults(handler=cmd_bless)

    p_doctor = loop_subs.add_parser(
        "doctor", help="report all five loop obligations at once, with the fix for each"
    )
    _common(p_doctor)
    p_doctor.add_argument("--corpus", default="corpus")
    p_doctor.add_argument("--agent-path", default="agents/demo/graph.py")
    p_doctor.add_argument("--observations", default=None)
    p_doctor.set_defaults(handler=cmd_doctor)
