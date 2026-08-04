"""`aef` CLI entry point: init, adopt, doctor, run, eval, trace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aef.cli.adopt import run_adopt
from aef.cli.doctor import run_doctor
from aef.cli.eval import eval_run
from aef.cli.init import run_init
from aef.cli.run import run_graph_module
from aef.cli.trace import trace_run


def _cmd_init(args: argparse.Namespace) -> int:
    result = run_init(args.agent_name, Path(args.dir))
    for path in result.written_files:
        print(f"wrote {path}")
    for path in result.skipped_files:
        print(f"skipped {path} (already exists)")
    return 0


def _cmd_adopt(args: argparse.Namespace) -> int:
    result = run_adopt(Path(args.dir))
    print(f"detected framework: {result.framework}")
    for path in result.written_files:
        print(f"wrote {path}")
    for path in result.skipped_files:
        print(f"skipped {path} (already exists)")
    print("\nmigration checklist:")
    for i, item in enumerate(result.checklist, 1):
        print(f"  {i}. {item}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_doctor(Path(args.dir))
    all_ok = True
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")
        all_ok = all_ok and check.ok
    return 0 if all_ok else 1


def _cmd_run(args: argparse.Namespace) -> int:
    state = run_graph_module(
        args.module,
        agent_id=args.agent_id,
        objective=args.objective,
        config_path=args.config,
        checkpoints_dir=args.checkpoints_dir,
    )
    print(state.model_dump_json(indent=2))
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    record = eval_run(Path(args.checkpoints_dir), args.run_id)
    print(f"task_completion={record.task_completion}")
    print(f"tool_call_accuracy={record.tool_call_accuracy}")
    print(f"trajectory_quality={record.trajectory_quality}")
    print(f"cost_tokens={record.cost_tokens}")
    print(f"cost_dollars={record.cost_dollars}")
    print(f"latency_ms={record.latency_ms}")
    print(f"domain_gates={record.domain_gates}")
    print(f"passed={record.passed}")
    return 0 if record.passed else 1


def _cmd_trace(args: argparse.Namespace) -> int:
    provenance = trace_run(Path(args.checkpoints_dir), args.run_id)
    for p in provenance:
        line = (
            f"{p.ts.isoformat()}  node={p.node_id}  model={p.model}  "
            f"tokens={p.token_cost}  trace_id={p.trace_id}"
        )
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aef", description="Agent Engineering Foundation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init", help="scaffold a brand-new agent")
    p_init.add_argument("agent_name")
    p_init.add_argument("--dir", default=".")
    p_init.set_defaults(handler=_cmd_init)

    p_adopt = subparsers.add_parser("adopt", help="migrate an existing repo onto AEF")
    p_adopt.add_argument("--dir", default=".")
    p_adopt.set_defaults(handler=_cmd_adopt)

    p_doctor = subparsers.add_parser("doctor", help="sanity-check an AEF setup")
    p_doctor.add_argument("--dir", default=".")
    p_doctor.set_defaults(handler=_cmd_doctor)

    p_run = subparsers.add_parser("run", help="run a graph module's build_graph()")
    p_run.add_argument("module", help="importable module path exposing build_graph()")
    p_run.add_argument("--agent-id", default="cli-agent")
    p_run.add_argument("--objective", required=True)
    p_run.add_argument(
        "--config", default=None, help="aef.yaml path; wires a real model_provider if given"
    )
    p_run.add_argument(
        "--checkpoints-dir",
        default=None,
        help="persist checkpoints here (FileDurabilityBackend) so `aef eval`/`aef trace` "
        "can find this run afterward; omit for a one-off in-memory run",
    )
    p_run.set_defaults(handler=_cmd_run)

    p_eval = subparsers.add_parser("eval", help="score a checkpointed run")
    p_eval.add_argument("--checkpoints-dir", required=True)
    p_eval.add_argument("--run-id", required=True)
    p_eval.set_defaults(handler=_cmd_eval)

    p_trace = subparsers.add_parser("trace", help="print a checkpointed run's provenance trail")
    p_trace.add_argument("--checkpoints-dir", required=True)
    p_trace.add_argument("--run-id", required=True)
    p_trace.set_defaults(handler=_cmd_trace)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    try:
        return int(handler(args))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
