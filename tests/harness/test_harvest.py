"""Corpus auto-growth. Every promotion path exercised against real runs.

The rules exist because their opposites each break the corpus in a different
way, so each has its own test and its own reason.
"""

import functools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aef.harness.corpus import (
    Expected,
    Scenario,
    Source,
    Split,
    load_corpus,
    save_scenario,
)
from aef.harness.harvest import (
    RecordedRun,
    _RecordedIsolation,
    harvest,
    load_runs,
    save_run,
)
from aef.kernel import END, Context, Graph, GraphExecutor, Node, Route, Services
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
    ProviderMessage,
)
from aef.providers.cassette_provider import CassetteProvider
from aef.reasoning.prompt_agent import (
    CONTAINMENT_SUFFIX,
    PromptAgentDefinition,
    make_prompt_agent_node,
)
from aef.state import AEFState, Plan, StateDelta

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _graph(*, always_succeed: bool = False) -> Graph:
    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        should_fail = bool(state.working_memory.get("fail")) and not always_succeed
        if should_fail:
            return StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[{"node_id": ctx.node_id, "error": "boom"}],
            ), END
        return StateDelta(plan=Plan(goal=state.objective, status="done")), END

    node = Node(id="work", version="0.1.0", fn=work, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"work": node}, edges=[], entry_node="work")


def _record(runs: Path, run_id: str, *, fail: bool, at: datetime | None = None) -> RecordedRun:
    graph = _graph()
    state = AEFState(
        run_id=run_id, agent_id="demo", objective="task", working_memory={"fail": fail}
    )
    ticks = iter([NOW + timedelta(seconds=i) for i in range(20)])
    result = GraphExecutor(graph.compile(), Services(clock=lambda: next(ticks))).run(
        state, record_trace=True
    )
    assert result.trace is not None
    run = RecordedRun(
        run_id=run_id,
        graph_id=graph.id,
        graph_version=graph.version,
        initial_state=state,
        trace=result.trace,
        at=at or NOW,
    )
    save_run(runs, run)
    return run


def _harvest(tmp_path: Path, **kwargs: object):
    return harvest(
        tmp_path / "runs", tmp_path / "corpus", _graph(), now=NOW + timedelta(hours=1), **kwargs
    )  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------


def test_a_recorded_run_round_trips(tmp_path: Path) -> None:
    original = _record(tmp_path / "runs", "r1", fail=True)
    loaded = load_runs(tmp_path / "runs")
    assert len(loaded) == 1
    assert loaded[0].run_id == original.run_id
    assert loaded[0].initial_state == original.initial_state


def test_a_failing_run_is_recognised_as_failed(tmp_path: Path) -> None:
    assert _record(tmp_path / "runs", "r1", fail=True).failed


def test_a_passing_run_is_not(tmp_path: Path) -> None:
    assert not _record(tmp_path / "runs", "r2", fail=False).failed


def test_a_missing_runs_directory_reads_as_empty(tmp_path: Path) -> None:
    assert load_runs(tmp_path / "nope") == ()


# --------------------------------------------------------------------------
# Failures promoted, successes not
# --------------------------------------------------------------------------


def test_a_failing_run_is_promoted(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "fail-1", fail=True)
    outcome = _harvest(tmp_path)

    assert outcome.promoted == ("fail-1",)
    assert {s.id for s in load_corpus(tmp_path / "corpus").scenarios} == {"fail-1"}


def test_a_passing_run_is_not_promoted_by_default(tmp_path: Path) -> None:
    """Auto-promoting successes inflates the pass rate the gates measure
    against, so the corpus drifts toward 'everything passes' — and a corpus
    where everything passes cannot demonstrate an improvement."""
    _record(tmp_path / "runs", "pass-1", fail=False)
    outcome = _harvest(tmp_path)

    assert outcome.promoted == ()
    assert outcome.skipped_passing == ("pass-1",)


def test_a_passing_run_is_promoted_on_request(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "pass-1", fail=False)
    assert _harvest(tmp_path, include_successes=True).promoted == ("pass-1",)


# --------------------------------------------------------------------------
# Always TRAIN, and no owner claim
# --------------------------------------------------------------------------


def test_harvested_scenarios_land_in_train(tmp_path: Path) -> None:
    # If production could write to validation, the set that gates candidates
    # would be shaped by the same system being gated.
    _record(tmp_path / "runs", "fail-1", fail=True)
    _harvest(tmp_path)

    corpus = load_corpus(tmp_path / "corpus")
    assert [s.split for s in corpus.scenarios] == [Split.TRAIN]
    assert corpus.split(Split.VALIDATION) == ()
    assert corpus.split(Split.HOLDOUT) == ()


def test_harvest_offers_no_way_to_choose_a_split(tmp_path: Path) -> None:
    import inspect

    from aef.harness.harvest import harvest as harvest_fn

    assert "split" not in inspect.signature(harvest_fn).parameters


def test_a_harvested_scenario_carries_no_owner_claim(tmp_path: Path) -> None:
    """Only a human can say a task SHOULD have failed. A MUST_FAIL label the
    system invented would be a tripwire it set for itself."""
    _record(tmp_path / "runs", "fail-1", fail=True)
    _harvest(tmp_path)

    scenario = load_corpus(tmp_path / "corpus").scenarios[0]
    assert scenario.expected is Expected.UNSPECIFIED


# --------------------------------------------------------------------------
# Determinism, duplicates, rate limit
# --------------------------------------------------------------------------


def test_a_run_that_does_not_reproduce_is_rejected(tmp_path: Path) -> None:
    """One admitted flake poisons every future comparison — the cost is not
    one bad scenario, it is a corpus nobody can trust."""
    _record(tmp_path / "runs", "flaky-1", fail=True)

    # The recorded run failed; this graph succeeds on the same input, so
    # re-execution produces a different trace. Whether the divergence comes
    # from nondeterminism or from the graph having moved on, the scenario
    # cannot be trusted as a fixed point and must not be admitted.
    outcome = harvest(
        tmp_path / "runs",
        tmp_path / "corpus",
        _graph(always_succeed=True),
        now=NOW + timedelta(hours=1),
    )

    assert outcome.promoted == ()
    assert outcome.rejected_nondeterministic == ("flaky-1",)
    assert not (tmp_path / "corpus").exists() or not load_corpus(tmp_path / "corpus").scenarios


def test_an_already_harvested_run_is_not_promoted_twice(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "fail-1", fail=True)
    _harvest(tmp_path)

    second = _harvest(tmp_path)
    assert second.promoted == ()
    assert second.skipped_existing == ("fail-1",)


def test_the_daily_rate_limit_caps_promotions(tmp_path: Path) -> None:
    # One bad deploy can produce thousands of failing runs; without a cap the
    # corpus fills with a single incident and the gates measure that instead.
    for i in range(9):
        _record(tmp_path / "runs", f"fail-{i}", fail=True)

    outcome = _harvest(tmp_path, daily_limit=3)

    assert len(outcome.promoted) == 3
    assert len(outcome.skipped_rate_limited) == 6


def test_the_rate_limit_counts_what_was_already_recorded_today(tmp_path: Path) -> None:
    for i in range(4):
        _record(tmp_path / "runs", f"fail-{i}", fail=True)
    first = _harvest(tmp_path, daily_limit=2)
    assert len(first.promoted) == 2

    second = _harvest(tmp_path, daily_limit=2)
    assert second.promoted == (), "the limit must span runs, not reset per invocation"


def _bootstrapped(root: Path, count: int, *, at: datetime) -> None:
    """`count` scenarios recorded today by a command that is not harvest."""
    graph = _graph()
    for i in range(count):
        state = AEFState(
            run_id=f"boot-{i}", agent_id="demo", objective="task", working_memory={"fail": False}
        )
        ticks = iter([at + timedelta(seconds=j) for j in range(20)])
        clock = functools.partial(next, ticks)
        result = GraphExecutor(graph.compile(), Services(clock=clock)).run(state, record_trace=True)
        assert result.trace is not None
        save_scenario(
            root,
            Scenario(
                id=f"boot-{i}",
                split=Split.TRAIN,
                graph_id=graph.id,
                graph_version=graph.version,
                initial_state=state,
                trace=result.trace,
                recorded_at=at,
                source=Source.BOOTSTRAP,
            ),
        )


def test_bootstrap_does_not_spend_harvests_daily_budget(tmp_path: Path) -> None:
    """The K5 pilot sequence is adopt, bootstrap, run for real, harvest — and
    it silently dropped every real production failure.

    `already_today` counted every scenario recorded in the last 24 hours and
    `bootstrap` stamps `recorded_at = now` on all of its, so a 12-input
    bootstrap exhausted a limit of 5: `promoted 0 run(s)`,
    `3 held back by the daily rate limit`, exit 0 (reproduced, ADR 0141).
    """
    _bootstrapped(tmp_path / "corpus", 12, at=NOW)
    for i in range(3):
        _record(tmp_path / "runs", f"real-{i}", fail=True)

    outcome = _harvest(tmp_path, daily_limit=5)

    assert len(outcome.promoted) == 3, outcome.lines
    assert outcome.skipped_rate_limited == ()


def test_harvests_own_promotions_still_spend_it(tmp_path: Path) -> None:
    """The narrowing must not have removed the limit. One bad deploy is still
    one bad deploy."""
    _bootstrapped(tmp_path / "corpus", 12, at=NOW)
    for i in range(6):
        _record(tmp_path / "runs", f"real-{i}", fail=True)

    outcome = _harvest(tmp_path, daily_limit=2)

    assert len(outcome.promoted) == 2
    assert len(outcome.skipped_rate_limited) == 4


def test_the_held_back_line_says_what_spent_the_budget(tmp_path: Path) -> None:
    """ "held back by the daily rate limit" named a rule and no arithmetic, so
    a run held back by a budget something else had consumed read exactly like
    one held back by harvest's own volume (ADR 0141)."""
    _bootstrapped(tmp_path / "corpus", 4, at=NOW)
    for i in range(4):
        _record(tmp_path / "runs", f"real-{i}", fail=True)

    outcome = _harvest(tmp_path, daily_limit=2)
    text = "\n".join(outcome.lines)

    assert "held back by the daily rate limit" in text
    assert "the limit is 2 HARVESTED scenario(s) per 24h" in text
    assert "0 had been harvested before this run and 2 were promoted by it" in text
    assert "4 from bootstrap" in text
    assert "do NOT count against it" in text


def test_a_harvested_scenario_records_that_harvest_wrote_it(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "r1", fail=True)
    _harvest(tmp_path)
    (scenario,) = load_corpus(tmp_path / "corpus").scenarios
    assert scenario.source is Source.HARVEST


def test_the_outcome_reports_every_category(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "fail-1", fail=True)
    _record(tmp_path / "runs", "pass-1", fail=False)
    lines = " ".join(_harvest(tmp_path).lines)

    assert "promoted 1" in lines
    assert "passed, not promoted" in lines


# --------------------------------------------------------------------------
# A run whose graph calls a model (ADR 0126)
# --------------------------------------------------------------------------


class _OneShotProvider(ModelProvider):
    """Answers once and refuses ever after. A recording gets its answer; any
    later caller that reaches for the model instead of the cassette fails
    loudly rather than quietly producing a second, different answer."""

    name = "one-shot"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("the cassette was bypassed: the live provider was called again")
        return CompletionResult(
            content="the model said so", model="fake-1", input_tokens=3, output_tokens=5
        )


def _model_graph() -> Graph:
    def ask(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        reply = services.require_model_provider().complete(
            CompletionRequest(
                messages=(ProviderMessage(role="user", content=state.objective),),
                model="fake-1",
                max_tokens=64,
            )
        )
        return StateDelta(
            plan=Plan(goal=state.objective, status="failed"),
            errors=[{"node_id": ctx.node_id, "error": f"boom: {reply.content}"}],
        ), END

    node = Node(id="ask", version="0.1.0", fn=ask, deterministic=False)
    return Graph(id="mg", version="0.1.0", nodes={"ask": node}, edges=[], entry_node="ask")


def _record_model_run(
    runs: Path, run_id: str, provider: _OneShotProvider | None = None
) -> tuple[RecordedRun, _OneShotProvider]:
    """What `aef run --record-runs` must do once the recording side is wired:
    wrap the configured provider in a recording cassette and carry
    `recording.recorded` into the `RecordedRun`."""
    graph = _model_graph()
    state = AEFState(run_id=run_id, agent_id="demo", objective="task", working_memory={})
    ticks = iter([NOW + timedelta(seconds=i) for i in range(20)])
    live = provider or _OneShotProvider()
    recording = CassetteProvider(live, on_miss="live")
    services = Services(clock=lambda: next(ticks), model_provider=recording)
    result = GraphExecutor(graph.compile(), services).run(state, record_trace=True)
    assert result.trace is not None
    run = RecordedRun(
        run_id=run_id,
        graph_id=graph.id,
        graph_version=graph.version,
        initial_state=state,
        trace=result.trace,
        at=NOW,
        model_calls=recording.recorded,
    )
    save_run(runs, run)
    return run, live


def test_a_model_calling_run_harvests_and_re_executes_from_its_cassette(tmp_path: Path) -> None:
    """Reproduced before the fix: harvest pinned the clock and not the model,
    so this run re-executed against no provider, raised, and was rejected as
    `rejected_nondeterministic` — the verdict a flaky run gets, for a run that
    reproduces exactly."""
    run, live = _record_model_run(tmp_path / "runs", "m1")
    assert len(run.model_calls) == 1
    outcome = harvest(
        tmp_path / "runs",
        tmp_path / "corpus",
        _model_graph(),
        now=NOW + timedelta(hours=1),
    )
    assert outcome.rejected_nondeterministic == ()
    assert outcome.promoted == ("m1",)
    # The re-executions ran off the cassette, never off the live provider.
    assert live.calls == 1
    # And the cassette travels into the corpus, so the gates can replay it too.
    scenario = load_corpus(tmp_path / "corpus").scenarios[0]
    assert len(scenario.model_calls) == 1
    assert scenario.model_calls[0].result.content == "the model said so"


def test_the_cassettes_own_request_digest_is_not_read_as_a_secret(tmp_path: Path) -> None:
    """`RecordedCall.key` is a 64-char SHA-256 the harness computes from the
    request. Scanned as tenant text it matches `opaque_secret` every time, and
    every model-calling run was rejected as "a secret survived redaction"."""
    _record_model_run(tmp_path / "runs", "m1")
    outcome = harvest(
        tmp_path / "runs", tmp_path / "corpus", _model_graph(), now=NOW + timedelta(hours=1)
    )
    assert outcome.rejected_unredactable == ()
    assert outcome.promoted == ("m1",)


def test_a_secret_in_the_models_reply_still_fails_the_output_scan(tmp_path: Path) -> None:
    """The control the previous test must not weaken: the request and the
    reply are still scanned in full."""

    class _Leaking(_OneShotProvider):
        def complete(self, request: CompletionRequest) -> CompletionResult:
            result = super().complete(request)
            return CompletionResult(
                content="upstream said sk-live-4f8a9b2c1d0e7f6a5b4c3d2e1f0a9b8c",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

    run, _live = _record_model_run(tmp_path / "runs", "m1", provider=_Leaking())
    outcome = harvest(
        tmp_path / "runs", tmp_path / "corpus", _model_graph(), now=NOW + timedelta(hours=1)
    )
    assert outcome.rejected_unredactable == ("m1",)
    assert outcome.promoted == ()


def test_a_recorded_runs_model_calls_round_trip(tmp_path: Path) -> None:
    run, _live = _record_model_run(tmp_path / "runs", "m1")
    loaded = load_runs(tmp_path / "runs")[0]
    assert loaded.model_calls == run.model_calls


def test_a_run_recorded_before_the_cassette_loads_with_none(tmp_path: Path) -> None:
    """Legacy payloads have no `model_calls` key and must still load."""
    runs = tmp_path / "runs"
    _record(runs, "r1", fail=True)
    path = next(runs.glob("*.json"))
    payload = json.loads(path.read_text())
    assert payload.pop("model_calls") == []
    path.write_text(json.dumps(payload))
    assert load_runs(runs)[0].model_calls == ()


# --------------------------------------------------------------------------
# The containment declaration the re-check could not reproduce (ADR 0190,
# closing ADR 0163's F-M6-2)
# --------------------------------------------------------------------------


class _IsolatedProvider(_OneShotProvider):
    """A provider that DECLARES containment, the way every real one does
    (ADR 0169). `command`'s declaration is the owner's `isolation:` list;
    `claude_code`'s is derived from the argv it actually builds."""

    name = "isolated"

    @property
    def isolation(self) -> frozenset[str]:
        return frozenset({"no_tools", "single_turn", "system_role"})


def _prompt_agent_graph() -> Graph:
    """The real node `aef migrate` generates, built from a definition rather
    than a file — the thing under test is harvest's re-execution, and a
    hand-written stand-in would not write the containment record the way the
    node does."""
    node = make_prompt_agent_node(
        definition=PromptAgentDefinition(name="answerer", description="d", body="You answer."),
        agent_name="answerer",
        route=END,
    )
    return Graph(id="pa", version="0.1.0", nodes={node.id: node}, edges=[], entry_node=node.id)


def _record_prompt_agent_run(runs: Path, run_id: str, *, isolation: bool = True) -> RecordedRun:
    """What `aef run --record-runs` does since ADR 0190: wrap the configured
    provider in a recording cassette, and carry BOTH what the model said and
    what the provider declared onto the run."""
    graph = _prompt_agent_graph()
    state = AEFState(run_id=run_id, agent_id="demo", objective="task", working_memory={})
    ticks = iter([NOW + timedelta(seconds=i) for i in range(20)])
    live: ModelProvider = _IsolatedProvider() if isolation else _OneShotProvider()
    recording = CassetteProvider(live, on_miss="live")
    result = GraphExecutor(
        graph.compile(), Services(clock=lambda: next(ticks), model_provider=recording)
    ).run(state, record_trace=True)
    assert result.trace is not None
    run = RecordedRun(
        run_id=run_id,
        graph_id=graph.id,
        graph_version=graph.version,
        initial_state=state,
        trace=result.trace,
        at=NOW,
        model_calls=recording.recorded,
        provider_isolation=tuple(sorted(recording.isolation)),
        provider_name=live.name,
    )
    save_run(runs, run)
    return run


def _containment(run: RecordedRun) -> object:
    for record in run.trace:
        for key, value in (record.delta.working_memory or {}).items():
            if key.endswith(CONTAINMENT_SUFFIX):
                return value
    raise AssertionError("the run recorded no containment block")


def test_a_prompt_agent_run_carries_the_providers_declaration(tmp_path: Path) -> None:
    run = _record_prompt_agent_run(tmp_path / "runs", "pa-1")
    assert run.provider_isolation == ("no_tools", "single_turn", "system_role")
    assert _containment(run) == {
        "provider": "cassette",
        "isolation": ["no_tools", "single_turn", "system_role"],
        "persona_role": "system",
    }


def test_a_prompt_agent_run_is_harvested_into_the_corpus(tmp_path: Path) -> None:
    """ADR 0163's F-M6-2: with the cassette supplied and no declaration
    replayed, the re-execution wrote `isolation: [], persona_role: 'unknown'`
    against the recorded values, and the byte-for-byte trace comparison
    rejected every run of every `aef migrate`-generated graph, on any repo."""
    _record_prompt_agent_run(tmp_path / "runs", "pa-1")
    outcome = harvest(
        tmp_path / "runs",
        tmp_path / "corpus",
        _prompt_agent_graph(),
        now=NOW + timedelta(hours=1),
        include_successes=True,
    )
    assert outcome.rejected_nondeterministic == ()
    assert outcome.promoted == ("pa-1",)


def test_a_run_that_recorded_no_declaration_still_replays_as_no_claim(tmp_path: Path) -> None:
    """The empty set is *no claim*, not "nothing is enforced" (ADR 0169), and
    a run recorded under a provider that declared nothing must still harvest:
    both sides say nothing, so both sides agree."""
    run = _record_prompt_agent_run(tmp_path / "runs", "pa-2", isolation=False)
    assert run.provider_isolation == ()
    outcome = harvest(
        tmp_path / "runs",
        tmp_path / "corpus",
        _prompt_agent_graph(),
        now=NOW + timedelta(hours=1),
        include_successes=True,
    )
    assert outcome.promoted == ("pa-2",)


def test_a_declaration_the_replay_cannot_reproduce_is_still_rejected(tmp_path: Path) -> None:
    """THE control, and it must be exactly as strict as it was before.

    The fix replays a RECORDED fact; it does not stop comparing the fact. A
    run whose recorded containment disagrees with what its own declaration
    reproduces is a run whose behaviour changed, and it is rejected — this is
    the case that would be silently admitted if the comparison had instead
    been taught to ignore `*__containment` keys (option (b), ADR 0190).
    """
    runs = tmp_path / "runs"
    _record_prompt_agent_run(runs, "pa-3")
    path = next(runs.glob("*.json"))
    payload = json.loads(path.read_text())
    assert payload["provider_isolation"] == ["no_tools", "single_turn", "system_role"]
    # A persona that went out in the SYSTEM turn, replayed as one that went
    # out in the user turn: the same run, a different containment fact.
    payload["provider_isolation"] = ["single_turn", "user_turn_persona"]
    path.write_text(json.dumps(payload))

    outcome = harvest(
        runs,
        tmp_path / "corpus",
        _prompt_agent_graph(),
        now=NOW + timedelta(hours=1),
        include_successes=True,
    )
    assert outcome.promoted == ()
    assert outcome.rejected_nondeterministic == ("pa-3",)


def test_the_re_execution_never_reaches_a_live_provider() -> None:
    """`_RecordedIsolation` carries a declaration and answers nothing: a
    harvest that reached the network to decide whether a run is deterministic
    has already lost the property it is checking."""
    provider = _RecordedIsolation(("no_tools",), "command")
    assert provider.isolation == frozenset({"no_tools"})
    assert provider.name == "command"
    with pytest.raises(ModelProviderError):
        provider.complete(
            CompletionRequest(messages=(ProviderMessage(role="user", content="x"),), model="m")
        )


def test_a_run_recorded_before_the_declaration_existed_loads_with_none(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _record(runs, "r1", fail=True)
    path = next(runs.glob("*.json"))
    payload = json.loads(path.read_text())
    assert payload.pop("provider_isolation") == []
    assert payload.pop("provider_name") == ""
    path.write_text(json.dumps(payload))
    loaded = load_runs(runs)[0]
    assert loaded.provider_isolation == ()
    assert loaded.provider_name == ""


# --------------------------------------------------------------------------
# One graph per invocation (ADR 0190; ADR 0163 §6's third observation)
# --------------------------------------------------------------------------


def test_a_run_of_another_graph_is_not_re_executed_against_this_one(tmp_path: Path) -> None:
    """`harvest()` iterated the runs directory with no `graph_id` filter and
    stamped each promoted scenario with the RUN's graph id while having
    re-executed it against the graph on the command line, so a run that
    happened to reproduce would enter the corpus labelled one graph and
    tracing another. It was masked only by F-M6-1: a foreign run missed the
    cassette and was reported as flaky instead."""
    runs = tmp_path / "runs"
    _record(runs, "mine-1", fail=True)
    other = _record(runs, "theirs-1", fail=True)
    path = runs / f"{other.run_id}.json"
    payload = json.loads(path.read_text())
    payload["graph_id"] = "some-other-graph"
    path.write_text(json.dumps(payload))

    outcome = _harvest(tmp_path)
    assert outcome.promoted == ("mine-1",)
    assert outcome.skipped_other_graph == ("theirs-1",)
    assert outcome.rejected_nondeterministic == ()
    assert "recorded from another graph, not re-executed here" in " ".join(outcome.lines)
    assert {s.graph_id for s in load_corpus(tmp_path / "corpus").scenarios} == {"g"}


def test_the_harness_run_id_is_held_out_of_the_scan_wherever_it_appears() -> None:
    """ADR 0192's F-N7-4. The run id is not only the scenario's `id` and its
    `initial_state.run_id`: it is threaded through every trace record's
    `input_state.run_id` and its `context.run_id`, `trace_id` and
    `idempotency_key`. ADR 0197 gave the policy a `uuid` pattern, so the
    output scan rejected every recorded run for carrying its own identifier.
    Held out by VALUE — a path list would grow silently the next time a field
    carries it."""
    from aef.harness.harvest import _blank_values
    from aef.harness.redaction import RedactionPolicy

    rid = "512e9cc3-23e8-410d-8b3a-358c55c106b8"
    payload = {
        "id": rid,
        "initial_state": {"run_id": rid},
        "trace": [
            {
                "input_state": {"run_id": rid},
                "context": {"run_id": rid, "trace_id": rid, "idempotency_key": rid},
            }
        ],
    }
    assert RedactionPolicy().find(payload) == ("uuid",), "the defect, before the hold-out"
    assert not RedactionPolicy().find(_blank_values(payload, {rid}))


def test_a_uuid_that_is_not_the_harness_own_still_rejects() -> None:
    """The other side: only THIS scenario's identifiers are held out."""
    from aef.harness.harvest import _blank_values
    from aef.harness.redaction import RedactionPolicy

    mine = "512e9cc3-23e8-410d-8b3a-358c55c106b8"
    theirs = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    payload = {"id": mine, "trace": [{"context": {"run_id": mine}, "note": theirs}]}
    held = _blank_values(payload, {mine})
    assert RedactionPolicy().find(held) == ("uuid",), "a foreign UUID must still be seen"
    assert mine not in str(held)
