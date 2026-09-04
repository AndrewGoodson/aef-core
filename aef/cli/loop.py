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

from aef.harness.checks import TaskCheck
from aef.harness.corpus import Expected, Split, load_corpus
from aef.harness.git import GitRepo
from aef.harness.loop import (
    EXIT_HALTED,
    EXIT_OK,
    EXIT_REJECTED,
    PROPOSERS,
    CorpusGraphMismatchError,
    KeptBranchCheckedOutError,
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
from aef.providers.base import ModelProvider


def _build_commands(args: argparse.Namespace) -> tuple[tuple[str, ...], ...] | None:
    """Repo-specific build commands, or None to take G1's default.

    Each `--build-command` is a whole shell-free command, split on spaces.
    Repeatable, because a green bar is usually more than one command.
    """
    raw = getattr(args, "build_command", None)
    if not raw:
        return None
    return tuple(tuple(c.split()) for c in raw)


def _proposer(args: argparse.Namespace) -> tuple[str, ModelProvider | None, str | None]:
    """`--proposer llm` builds the harness provider (ADR 0112: the session's
    own login, no key) for the model `--proposer-model` names. The default
    is rule-based, by measurement (ADR 0122)."""
    proposer = getattr(args, "proposer", "rule_based")
    if proposer != "llm":
        return proposer, None, None
    model = getattr(args, "proposer_model", None)
    if not model:
        raise ValueError("--proposer llm needs --proposer-model <model id>")
    from aef.config.factory import build_model_provider
    from aef.config.schema import ModelProviderConfig

    return (
        proposer,
        build_model_provider(ModelProviderConfig(impl="claude_code", model=model)),
        model,
    )


def _config(args: argparse.Namespace) -> LoopConfig:
    corpus_dir = Path(args.corpus) if getattr(args, "corpus", None) else None
    proposer, proposer_provider, proposer_model = _proposer(args)
    return LoopConfig(
        proposer=proposer,
        proposer_provider=proposer_provider,
        proposer_model=proposer_model,
        repo=GitRepo(root=Path(args.repo)),
        paths=LoopPaths(root=Path(args.state)),
        base_ref=getattr(args, "base", "main"),
        graph_id=args.graph_id,
        corpus=load_corpus(corpus_dir) if corpus_dir and corpus_dir.is_dir() else None,
        network_isolated=bool(getattr(args, "network_isolated", False)),
        sandbox_image=getattr(args, "sandbox_image", None),
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
        # "fail" unless the owner asked for live scoring by name (ADR 0123).
        cassette_miss=getattr(args, "cassette_miss", "fail"),
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
    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.services.runtime import agent_services
    from aef.state import AEFState

    # The provider `aef run` would use, from the same config, so what gets
    # recorded is what production would have said. Absent, a graph that
    # calls a model records an errored run naming the miss (ADR 0123).
    model_provider = None
    reflection = "rule_based"
    reflection_model: str | None = None
    if getattr(args, "config", None):
        from aef.config import build_model_provider, load_agent_config

        config = load_agent_config(args.config)
        model_provider = build_model_provider(config.model_provider)
        reflection = config.reflection.impl
        reflection_model = config.model_provider.model

    try:
        checks = _parse_checks(getattr(args, "check", None))
    except (ValueError, TypeError) as exc:
        print(f"error: --check: {exc}", file=sys.stderr)
        return EXIT_REJECTED

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
        # Same list the gates use, so a scenario recorded here can be
        # re-executed there (aef/services/runtime.py, ADR 0091).
        agent_services(
            memory=InMemoryMemoryStore(),
            model_provider=model_provider,
            reflection=reflection,
            reflection_model=reflection_model,
            agent_id=args.agent_id,
        ),
        scenario_id=args.scenario_id,
        split=Split(args.split),
        recorded_at=datetime.now(UTC),
        notes=args.notes,
        allow_holdout=args.i_am_spending_the_holdout,
        expected=Expected(args.expected),
        checks=checks,
        budget_ms=getattr(args, "budget_ms", None),
    )
    print(f"recorded {recorded.scenario.id} ({recorded.scenario.split.value}) -> {recorded.path}")
    print(f"  {len(recorded.scenario.trace)} node execution(s) pinned")
    print(
        f"  {len(recorded.scenario.model_calls)} model call(s) pinned, "
        f"{len(recorded.scenario.checks)} check(s)"
    )
    return EXIT_OK


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """A corpus on day one: run the configured graph once per input and
    record each run as a TRAIN scenario (ADR 0138).

    Everything that makes this safe lives in `aef.harness.bootstrap` — train
    only, no `expected` label, no overwrite, and the failure count reported.
    This function is the boundary: it reads the file, builds the same
    services `aef loop record` builds, and prints.
    """
    from aef.cli.run import load_graph_module
    from aef.harness.bootstrap import BootstrapError, bootstrap, load_inputs
    from aef.harness.recorder import RecorderError
    from aef.kernel import Services
    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.services.runtime import agent_services

    # Bootstrap writes to corpus/, which IS the evidence every behavioural
    # gate is measured against, so it honours the same halt `harvest` does
    # (ADR 0069): a halted loop must not have its gate evidence changed
    # underneath it. `--state` is OPTIONAL here and required there, because
    # this is the day-one command and a loop state dir does not exist yet —
    # with no state dir there is no loop to have halted.
    if getattr(args, "state", None):
        try:
            LoopPaths(root=Path(args.state)).kill_switch.check()
        except LoopHaltedError as exc:
            print(f"HALTED: {exc}")
            return EXIT_HALTED

    graph = load_graph_module(args.module)

    # The provider `aef run` would use, from the same config, so what gets
    # recorded is what production would have said — identical to `record`.
    model_provider = None
    reflection = "rule_based"
    reflection_model: str | None = None
    if getattr(args, "config", None):
        from aef.config import build_model_provider, load_agent_config

        config = load_agent_config(args.config)
        model_provider = build_model_provider(config.model_provider)
        reflection = config.reflection.impl
        reflection_model = config.model_provider.model

    def services() -> Services:
        # A FACTORY, not one instance: each input gets its own memory store,
        # because the gates re-execute each scenario in isolation and a
        # scenario that only reproduces after its predecessors ran is one
        # nothing downstream can trust.
        return agent_services(
            memory=InMemoryMemoryStore(),
            model_provider=model_provider,
            reflection=reflection,
            reflection_model=reflection_model,
            agent_id=args.agent_id,
        )

    try:
        inputs = load_inputs(Path(args.inputs), prefix=args.prefix)
        outcome = bootstrap(
            Path(args.corpus),
            graph,
            services,
            inputs=inputs,
            now=datetime.now(UTC),
            agent_id=args.agent_id,
        )
    except (BootstrapError, RecorderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED

    for line in outcome.lines:
        print(line)
    for command in outcome.tripwire_commands(args.module, args.corpus, inputs):
        print(f"    {command}")
    # A command that recorded nothing did not seed a corpus, and a workflow
    # keying off exit 0 would believe it had. The ready loop's rule: the
    # tooling does not report green for something that did not happen.
    return EXIT_OK if outcome.recorded else EXIT_REJECTED


def _parse_checks(raw: list[str] | None) -> tuple[TaskCheck, ...]:
    """`--check` values: each a JSON object or a JSON list of objects.
    Malformed checks fail here, before anything runs — a check that loaded
    wrong would score the scenario 0 forever and read as a regression."""
    checks: list[TaskCheck] = []
    for item in raw or ():
        parsed = json.loads(item)
        entries = parsed if isinstance(parsed, list) else [parsed]
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"a check must be a JSON object, got {type(entry).__name__}")
            checks.append(TaskCheck.from_payload(entry))
    return tuple(checks)


def cmd_score(args: argparse.Namespace) -> int:
    """The task metric, read directly (ADR 0113): the incumbent graph over
    the corpus, one scalar per split with its honest statistics, and — with
    `--repeat` — the variance of that scalar across identical runs, which is
    the noise floor any claimed improvement has to clear.

    Runs in-process: this scores a graph the OWNER trusts (the incumbent),
    never a candidate. Candidates are scored by `loop gate`, isolated.
    Holdout is excluded unless asked for by name — it is the owner's only
    independent read, and reading it casually spends it.
    """
    from aef.harness.evaluation import ScoreSet
    from aef.harness.scenario_runner import load_graph, run_scenario

    corpus = load_corpus(Path(args.corpus))
    graph = load_graph(args.entrypoint)
    splits = [Split(s) for s in args.splits.split(",")]
    if Split.HOLDOUT in splits and not args.i_am_spending_the_holdout:
        print(
            "refusing to score the holdout split without --i-am-spending-the-holdout",
            file=sys.stderr,
        )
        return EXIT_REJECTED

    # Model calls replay from each scenario's cassette (ADR 0123). Under
    # --cassette-miss live the provider in --config answers what the
    # recording never saw, and the report says how many times it did: a
    # score with live misses is a different measurement from a replayed one.
    cassette_miss = getattr(args, "cassette_miss", "fail")
    live_provider = None
    # The OWNER'S policy, from the owner's own `aef.yaml` — the same one
    # `aef run --config` applies and the same one `_policy_from_base_ref`
    # hands the gates. This read `None`, so `loop score` judged every tool
    # call deny-by-default while both other paths allowed it: reproduced at
    # 0.0 here against 1.0 there, on identical code and one config file
    # (ADR 0125). Two lists that must agree, with nothing checking that they
    # did — ADR 0091's finding, in a third place.
    score_policy = None
    if getattr(args, "config", None):
        from aef.config import build_model_provider, build_policy_config, load_agent_config

        agent_config = load_agent_config(args.config)
        score_policy = build_policy_config(agent_config.tools, agent_config.policies)
        if cassette_miss == "live":
            live_provider = build_model_provider(agent_config.model_provider)

    # Only the scenarios recorded FROM this graph. A corpus may hold several
    # graphs' recordings (the demo's and the summary agent's); scoring one
    # graph against another's scenarios measures nothing about either.
    other_graph = sorted(s.id for s in corpus.scenarios if s.graph_id != graph.id)

    runs: list[dict[str, ScoreSet]] = []
    hits = misses = 0
    for _ in range(args.repeat):
        per_split: dict[str, ScoreSet] = {}
        for split in splits:
            scenarios = tuple(s for s in corpus.split(split) if s.graph_id == graph.id)
            per_scenario: dict[str, float] = {}
            cost = 0
            for scenario in scenarios:
                result = run_scenario(
                    scenario,
                    graph,
                    score_policy,
                    cassette_miss=cassette_miss,
                    live_provider=live_provider,
                )
                per_scenario[scenario.id] = float(result["score"])
                cost += int(result["cost_tokens"])
                stats = result.get("cassette", {})
                hits += int(stats.get("hits", 0))
                misses += int(stats.get("misses", 0))
            per_split[split.value] = ScoreSet(
                label=split.value, per_scenario=per_scenario, cost_tokens=cost
            )
        runs.append(per_split)

    report: dict[str, object] = {
        "entrypoint": args.entrypoint,
        "graph_id": graph.id,
        "repeat": args.repeat,
        "skipped_other_graph": other_graph,
        "cassette": {"on_miss": cassette_miss, "hits": hits, "misses": misses},
    }
    for split in splits:
        sets = [run[split.value] for run in runs]
        first = sets[0]
        if first.n == 0:
            report[split.value] = {"n": 0}
            continue
        means = [s.mean for s in sets]
        spread = max(means) - min(means)
        lo, hi = first.confidence_interval_95
        with_checks = sum(1 for s in corpus.split(split) if s.checks and s.graph_id == graph.id)
        report[split.value] = {
            "n": first.n,
            "with_checks": with_checks,
            "mean": round(first.mean, 4),
            "stdev": round(first.stdev, 4),
            "ci95": [round(lo, 4), round(hi, 4)],
            "cost_tokens": first.cost_tokens,
            "per_scenario": {k: round(v, 4) for k, v in sorted(first.per_scenario.items())},
            # Across identical runs. Anything an increment claims must exceed this.
            "repeat_mean_spread": round(spread, 6),
        }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return EXIT_OK
    print(f"task metric — {args.entrypoint} ({graph.id}) — repeat={args.repeat}")
    mode = "LIVE" if misses and cassette_miss == "live" else "replayed"
    print(
        f"  model calls: {hits} cassette hit(s), {misses} miss(es), "
        f"on_miss={cassette_miss} — {mode}"
    )
    if other_graph:
        print(f"  skipped {len(other_graph)} scenario(s) recorded from another graph")
    for split in splits:
        row = report[split.value]
        assert isinstance(row, dict)
        if row["n"] == 0:
            print(f"  {split.value:<11} n=0")
            continue
        print(
            f"  {split.value:<11} n={row['n']:<3} with_checks={row['with_checks']:<3} "
            f"mean={row['mean']:.4f} stdev={row['stdev']:.4f} "
            f"ci95=[{row['ci95'][0]:.4f}, {row['ci95'][1]:.4f}] "
            f"repeat_spread={row['repeat_mean_spread']:.6f}"
        )
        for sid, score in row["per_scenario"].items():
            print(f"      {score:.4f}  {sid}")
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
    except (PolicyConfigError, CorpusGraphMismatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED

    for line in run.lines:
        print(f"  {line}")
    return run.exit_code


def cmd_run(args: argparse.Namespace) -> int:
    """autoresearch's loop inside the gates (ADR 0114): N turns or a
    wall-clock budget, keep on a LOCAL branch, never main."""
    from aef.cli.run import load_graph_module
    from aef.harness.loop import run_loop
    from aef.harness.memory_store import FileMemoryStore

    config = _config(args)
    graph = load_graph_module(args.module) if args.module else None
    try:
        run = run_loop(
            config,
            now=datetime.now(UTC),
            workdir=Path(args.workdir),
            turns=args.turns,
            budget_seconds=args.budget_minutes * 60.0,
            kept_branch=args.kept_branch,
            runs_dir=Path(args.runs) if args.runs else None,
            corpus_root=Path(args.corpus) if args.corpus else None,
            graph=graph,
            memory=FileMemoryStore(path=Path(args.memory)) if args.memory else None,
            agent_path=args.agent_path,
        )
    except (PolicyConfigError, KeptBranchCheckedOutError, CorpusGraphMismatchError) as exc:
        # Named refusals, printed as one line rather than a traceback: each
        # names an operator action (stand somewhere else; pass --graph-id).
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except LoopHaltedError as exc:
        print(f"HALTED: {exc}")
        return EXIT_HALTED
    for line in run.lines:
        print(f"  {line}")
    print(
        f"kept {run.kept_count}, reverted {run.reverted_count}, "
        f"{run.kept_branch}@{run.kept_ref[:12]} — review and merge by hand; "
        f"Tier-1 auto-merge is off"
    )
    return EXIT_HALTED if "halted" in run.stopped_because else EXIT_OK


def cmd_skills(args: argparse.Namespace) -> int:
    """Draft skill proposals from the knowledge store (ADR 0117). Writes
    under --out only; never under .claude/, agents/ or any harness dir, and
    never over an existing draft."""
    from aef.harness.memory_store import FileMemoryStore
    from aef.harness.skills import SkillProposalError, propose_skills
    from aef.services.knowledge.consolidate import RuleBasedConsolidator
    from aef.services.knowledge.in_memory import InMemoryKnowledgeStore

    # The knowledge store is rebuilt from the durable memory store, because
    # the consolidator is a stateless recompute (ADR 0110) and no file-backed
    # knowledge store exists yet — the memory file IS the evidence.
    knowledge = InMemoryKnowledgeStore()
    RuleBasedConsolidator().consolidate(
        FileMemoryStore(path=Path(args.memory)), knowledge, agent_id=args.agent_id
    )
    try:
        proposals = propose_skills(
            knowledge,
            Path(args.out),
            agent_id=args.agent_id,
            min_occurrences=args.min_occurrences,
        )
    except SkillProposalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    for p in proposals:
        state = "wrote" if p.written else "kept existing"
        print(f"  {state} {p.path}  ({p.entry.occurrence_count} run(s))")
    print(
        f"{sum(p.written for p in proposals)} proposal(s) written, "
        f"{sum(not p.written for p in proposals)} left as-is. Nothing is adopted until a "
        f"person moves a draft under .claude/skills/."
    )
    return EXIT_OK


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

    def _proposer_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--proposer",
            choices=list(PROPOSERS),
            default="rule_based",
            help=(
                "which proposer writes the candidate. rule_based (default): numeric steps "
                "and the bounded structural catalogue, deterministic. llm: a model writes "
                "the whole file, code validates it against G0/G4 and falls back to "
                "rule_based on any failure (ADR 0122). Off by default, by measurement."
            ),
        )
        sub.add_argument(
            "--proposer-model",
            default=None,
            help="model id the llm proposer asks, through the claude_code harness login; "
            "required with --proposer llm, no default so no model id is hardcoded here",
        )

    def _cassette_miss(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--cassette-miss",
            default="fail",
            choices=["fail", "live"],
            help=(
                "what a model request the recording never saw does (ADR 0123). 'fail' "
                "(default): the node fails and the score is deterministic — no credential "
                "needed. 'live': the request goes to the provider in --config's "
                "model_provider and the score is a LIVE one, reported as such. Use it to "
                "score a prompt change on purpose, not to make a gate pass."
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
    _cassette_miss(p_gate)
    p_gate.add_argument(
        "--network-isolated",
        action="store_true",
        help="attest that the caller (a CI container) provides network isolation. "
        "A process cannot revoke its own network access; passing this without real "
        "isolation makes the sandbox's report untrue.",
    )
    p_gate.add_argument(
        "--sandbox-image",
        default=None,
        help="run candidate code inside a container built from this image, with "
        "--network none, --read-only and --cap-drop ALL. Unlike --network-isolated, "
        "which the caller ASSERTS, this is verified by a probe before anything runs — "
        "so the result's network_isolated=True is measured. Needs docker or podman; "
        "raises rather than degrading if neither is available.",
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
    p_record.add_argument(
        "--config",
        default=None,
        help=(
            "aef.yaml path; wires the real model_provider (e.g. impl: claude_code) so a "
            "graph that calls a model can be recorded. Every call it makes is pinned in "
            "the scenario and replayed by the gates without a credential (ADR 0123)."
        ),
    )
    p_record.add_argument(
        "--check",
        action="append",
        default=None,
        help=(
            "an OWNER check on the final state, as JSON: a single object "
            '\'{"path": "working_memory.summary", "op": "contains", "value": "X"}\' '
            "or a JSON list of them. Repeatable. Ops: equals, contains, regex, exists "
            "(ADR 0113). Data, never code."
        ),
    )
    p_record.add_argument(
        "--budget-ms",
        type=float,
        default=None,
        help="wall-clock budget for the re-execution, judged on the runner's stopwatch",
    )
    p_record.set_defaults(handler=cmd_record)

    p_bootstrap = loop_subs.add_parser(
        "bootstrap",
        help="a corpus on day one: run the graph once per input, record each as a scenario",
        description=(
            "INPUTS FILE SHAPE: a JSON list of objects, or an object with an "
            "'inputs' list. Each object needs `objective` (string) and may set "
            "`id` (default <prefix>-<n>), `working_memory` (object seeding "
            "AEFState.working_memory — how you reach the agent's FAILING cases), "
            "`notes`, `checks` (owner checks, ADR 0113) and `budget_ms`.\n\n"
            'EXAMPLE: [{"objective": "summarise the ticket", '
            '"working_memory": {"difficulty": 9}, '
            '"checks": [{"path": "scores.quality", "op": "equals", '
            '"value": 1.0}]}]\n\n'
            "WHAT IT WILL NOT DO. It writes the TRAIN split only and offers no "
            "flag to override, the same rule as `harvest`: if the system could "
            "fill the set that gates it, the gate would measure the system's own "
            "choices. It never labels `expected` — only an owner can say a task "
            "SHOULD have failed (ADR 0060) — and an `expected` key in the file is "
            "refused rather than ignored. It refuses the whole invocation if any "
            "id already exists, before running anything."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bootstrap.add_argument("module", help="importable module exposing build_graph()")
    p_bootstrap.add_argument("--corpus", required=True)
    p_bootstrap.add_argument(
        "--inputs", required=True, help="JSON file of inputs; see the description above"
    )
    p_bootstrap.add_argument(
        "--prefix",
        default="bootstrap",
        help="scenario id prefix for inputs that do not name one (default: bootstrap). "
        "Stable on purpose: re-running the same file is refused rather than "
        "overwriting what it recorded.",
    )
    p_bootstrap.add_argument("--agent-id", default="bootstrap")
    p_bootstrap.add_argument(
        "--state",
        default=None,
        help="loop state dir, if one exists. Optional, unlike every other loop "
        "subcommand: this is the day-one command and there may be no loop yet. Given "
        "one, an engaged kill switch stops the run — corpus/ is gate evidence, and a "
        "halted loop must not have it changed underneath it (ADR 0069).",
    )
    p_bootstrap.add_argument(
        "--config",
        default=None,
        help=(
            "aef.yaml path; wires the real model_provider (e.g. impl: claude_code) so a "
            "graph that calls a model can be recorded. Every call it makes is pinned in "
            "the scenario and replayed by the gates without a credential (ADR 0123)."
        ),
    )
    p_bootstrap.set_defaults(handler=cmd_bootstrap)

    p_score = loop_subs.add_parser(
        "score",
        help="the task metric: score the incumbent graph over the corpus",
        description=(
            "Scores IN-PROCESS. A scenario's `budget_ms` is judged on this "
            "stopwatch, and the gates' isolated path adds per-node IPC to the "
            "same measurement (~0.7 ms more on a 4-node graph, ADR 0113), so a "
            "budget calibrated here can fail at the gate — leave headroom."
        ),
    )
    p_score.add_argument("entrypoint", help="'module:factory' returning the incumbent Graph")
    p_score.add_argument("--corpus", required=True)
    p_score.add_argument(
        "--splits",
        default="train,validation",
        help="comma-separated; holdout needs --i-am-spending-the-holdout",
    )
    p_score.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run the whole suite N times and report the spread of the mean — the noise "
        "floor an improvement must clear",
    )
    p_score.add_argument("--json", action="store_true")
    p_score.add_argument("--i-am-spending-the-holdout", action="store_true")
    _cassette_miss(p_score)
    p_score.add_argument(
        "--config",
        default=None,
        help="aef.yaml path. Its tools/policies block is the policy the scored "
        "run gets — the same one `aef run --config` and the gates apply; without "
        "it the run is deny-by-default. Its model_provider also answers cassette "
        "misses under --cassette-miss live.",
    )
    p_score.set_defaults(handler=cmd_score)

    p_skills = loop_subs.add_parser(
        "skills", help="draft skill PROPOSALS from consolidated knowledge (never adopted here)"
    )
    p_skills.add_argument("--memory", required=True, help="durable memory store the agent wrote")
    p_skills.add_argument("--agent-id", required=True)
    p_skills.add_argument("--out", required=True, help="proposals dir; not a harness dir")
    p_skills.add_argument("--min-occurrences", type=int, default=3)
    p_skills.set_defaults(handler=cmd_skills)

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
    _cassette_miss(p_cycle)
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
    _proposer_flags(p_cycle)
    p_cycle.set_defaults(handler=cmd_cycle)

    p_run = loop_subs.add_parser(
        "run",
        help="N turns of propose -> gate -> keep-or-revert on a local kept branch (never main)",
    )
    _common(p_run)
    p_run.add_argument("--base", default="main")
    p_run.add_argument("--workdir", required=True)
    p_run.add_argument("--module", default=None, help="module exposing build_graph()")
    p_run.add_argument("--runs", default=None, help="dir from `aef run --record-runs`")
    p_run.add_argument("--corpus", default=None)
    p_run.add_argument("--config", default=None, help="aef.yaml path, read from the base ref")
    p_run.add_argument("--entrypoint", default=None, help="module:factory; G2/G3 refuse without it")
    _cassette_miss(p_run)
    p_run.add_argument("--memory", default=None, help="durable memory store the proposer reads")
    p_run.add_argument("--agent-path", default="agents/demo/graph.py")
    p_run.add_argument("--turns", type=int, default=10)
    p_run.add_argument("--budget-minutes", type=float, default=60.0)
    p_run.add_argument(
        "--kept-branch",
        default="loop/kept",
        help="local branch that advances on every kept candidate; a person merges it",
    )
    _proposer_flags(p_run)
    p_run.set_defaults(handler=cmd_run)

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
