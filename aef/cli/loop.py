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
from datetime import UTC, datetime
from pathlib import Path

from aef.harness.corpus import Split, load_corpus
from aef.harness.git import GitRepo
from aef.harness.loop import (
    EXIT_HALTED,
    EXIT_OK,
    LoopConfig,
    LoopPaths,
    default_digest_window,
)
from aef.harness.loop import digest as loop_digest
from aef.harness.loop import gate as loop_gate
from aef.harness.loop import monitor as loop_monitor
from aef.harness.loop import status as loop_status
from aef.harness.monitoring import LoopHaltedError
from aef.harness.recorder import record_to_corpus


def _config(args: argparse.Namespace) -> LoopConfig:
    corpus_dir = Path(args.corpus) if getattr(args, "corpus", None) else None
    return LoopConfig(
        repo=GitRepo(root=Path(args.repo)),
        paths=LoopPaths(root=Path(args.state)),
        base_ref=getattr(args, "base", "main"),
        graph_id=args.graph_id,
        corpus=load_corpus(corpus_dir) if corpus_dir and corpus_dir.is_dir() else None,
        network_isolated=bool(getattr(args, "network_isolated", False)),
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
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED

    print(run.report)
    if run.halted:
        print("\nLOOP HALTED — a proposal reached for the harness. Read the ledger.")
    return run.exit_code


def cmd_monitor(args: argparse.Namespace) -> int:
    config = _config(args)
    try:
        run = loop_monitor(config, now=datetime.now(UTC))
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
    result = loop_digest(config, since=since, until=until, owner_edits=args.owner_edits)
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
    from aef.state import AEFState

    recorded = record_to_corpus(
        Path(args.corpus),
        graph,
        AEFState(run_id=args.scenario_id, agent_id=args.agent_id, objective=args.objective),
        Services(),
        scenario_id=args.scenario_id,
        split=Split(args.split),
        recorded_at=datetime.now(UTC),
        notes=args.notes,
        allow_holdout=args.i_am_spending_the_holdout,
    )
    print(f"recorded {recorded.scenario.id} ({recorded.scenario.split.value}) -> {recorded.path}")
    print(f"  {len(recorded.scenario.trace)} node execution(s) pinned")
    return EXIT_OK


def add_loop_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("loop", help="drive the self-rewiring loop (gate/monitor/digest)")
    loop_subs = p.add_subparsers(dest="loop_command", required=True)

    def _common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--repo", default=".", help="git repository root")
        sub.add_argument(
            "--state", required=True, help="loop state dir (ledger, archive, kill switch)"
        )
        sub.add_argument("--graph-id", default="default")

    p_gate = loop_subs.add_parser("gate", help="evaluate one candidate branch")
    _common(p_gate)
    p_gate.add_argument("--base", default="main")
    p_gate.add_argument("--head", required=True)
    p_gate.add_argument("--workdir", required=True, help="scratch dir for gate execution")
    p_gate.add_argument("--corpus", default=None)
    p_gate.add_argument(
        "--network-isolated",
        action="store_true",
        help="attest that the caller (a CI container) provides network isolation. "
        "A process cannot revoke its own network access; passing this without real "
        "isolation makes the sandbox's report untrue.",
    )
    p_gate.set_defaults(handler=cmd_gate)

    p_monitor = loop_subs.add_parser("monitor", help="evaluate post-merge windows, auto-rollback")
    _common(p_monitor)
    p_monitor.set_defaults(handler=cmd_monitor)

    p_digest = loop_subs.add_parser("digest", help="weekly trend report")
    _common(p_digest)
    p_digest.add_argument("--json", action="store_true")
    p_digest.add_argument("--owner-edits", type=int, default=0)
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
    p_record.add_argument("--notes", default="")
    p_record.add_argument(
        "--i-am-spending-the-holdout",
        action="store_true",
        help="required to write to the holdout split. It is the owner's only independent "
        "read of whether the loop improves anything; filling it casually destroys that "
        "independence silently.",
    )
    p_record.set_defaults(handler=cmd_record)
