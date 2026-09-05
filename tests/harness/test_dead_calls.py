"""Classifying and retrying a model call that died (ADR 0185).

ADR 0156 established with `docs/research/i13/zero_signature.py`, and without
spending a call, that a provider which RAISES and a provider which returns
`""` both produce `score=0.0000, cost_tokens=0`. One such call accounted for
about a third of the live floor's spread. Under K1 (ADR 0181) every gate pass
may execute live, so every gate pass meets this.

The stub here is a **real provider running a real subprocess** — `impl:
command` pointed at a shell script that exits non-zero on chosen invocations,
the same substitution ADR 0181's offline tests use for `/bin/echo`. No test
in this file makes a model call.
"""

from __future__ import annotations

import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aef.harness.corpus import Scenario
from aef.harness.evaluation import ScoreSet
from aef.harness.isolated_suite import ScenarioResult, _failed, run_corpus_isolated
from aef.harness.recorder import record_run
from aef.harness.scenario_runner import _error_type_chain, is_dead_call
from aef.harness.suite import VariantRun
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider, ProviderMessage
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

RECORDED_AT = datetime(2026, 9, 5, tzinfo=UTC)

ASKER_SOURCE = """
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.state import Plan, StateDelta


def ask(state, ctx, services):
    result = services.require_model_provider().complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content=f"summarise: {state.objective}"),),
            model="",
        )
    )
    return (
        StateDelta(
            working_memory={"summary": result.content},
            plan=Plan(goal=state.objective, status="done"),
        ),
        END,
    )


def build_graph():
    return Graph(
        id="asker", version="1",
        nodes={"ask": Node(id="ask", version="1", fn=ask, deterministic=False,
                           side_effects=SideEffect.EXTERNAL_CALL,
                           idempotency_key_fn=lambda s: f"{s.run_id}:ask")},
        edges=[], entry_node="ask",
    )
"""

# The message `CassetteProvider` raises on a miss under `on_miss="fail"` —
# quoted rather than paraphrased, because the whole classification turns on
# this being a MISS rather than a death.
CASSETTE_MISS = (
    "ModelProviderError: cassette miss (key abc123, model '', 1 message(s), max_tokens 1024, "
    "first user text 'summarise: x'): no recorded completion for this request and "
    "on_miss='fail'."
)

# And the one raised under `on_miss="live"` with NOTHING to fall through to —
# quoted verbatim from the reproduction of ADR 0191's F1, because the whole
# classification turns on this naming an ABSENT provider rather than a dead
# one, and the two strings differ only in their tail.
NO_PROVIDER_MISS = (
    "NodeEvaluationError: ModelProviderError: cassette miss (key 6a9b6ea9c515, model '', "
    "1 message(s), max_tokens 16000, first user text 'summarise: the s1 passage') and no "
    "live provider to fall through to: on_miss='live' needs an inner ModelProvider "
    "(model_provider.impl in aef.yaml, e.g. claude_code — ADR 0112)"
)


# --------------------------------------------------------------------------
# The classifier
# --------------------------------------------------------------------------


def test_the_type_chain_stops_at_the_message() -> None:
    """A provider death arrives from the worker nested one deep, and the
    adapter's message may contain colons of its own."""
    assert _error_type_chain("NodeEvaluationError: ModelProviderError: claude: exited 1") == (
        "NodeEvaluationError",
        "ModelProviderError",
    )
    assert _error_type_chain("ValueError: nope") == ("ValueError",)
    assert _error_type_chain("no colon here") == ()
    # The limit, recorded rather than discovered: a candidate that spells the
    # name into another exception's message is classified as a death. The
    # retry and the refusal floor are what bound that, not this function.
    assert "ModelProviderError" in _error_type_chain("ModelProviderError: forged")


def test_a_provider_that_raised_on_a_live_run_is_a_dead_call() -> None:
    failure = "NodeEvaluationError: ModelProviderError: claude exited 1: rate limited"
    assert is_dead_call(failure, cassette_miss="live", live_provider_present=True)


def test_a_cassette_MISS_is_never_a_dead_call() -> None:
    """The load-bearing half. Under `on_miss="fail"` no call is attempted, so
    nothing can die — a `ModelProviderError` there is `CassetteProvider`
    reporting that the candidate asked something the recording never saw.

    That is a BEHAVIOURAL DIFFERENCE and the strongest signal the replayed
    path has: ADR 0123 caught the same planted regression ADR 0156 could not
    see live, scoring it 0.0000 with 36 misses. Excusing it as a dead call
    would throw that away."""
    assert not is_dead_call(CASSETTE_MISS, cassette_miss="fail", live_provider_present=True)
    # Same string, same exception type — the run's mode is what decides.
    assert is_dead_call(CASSETTE_MISS, cassette_miss="live", live_provider_present=True)


def test_nothing_else_is_a_dead_call() -> None:
    for failure in (
        None,
        "NodeEvaluationError: ZeroDivisionError: division by zero",
        "unusable check: refusing to run regex check ...",
        "IsolationError: worker produced no result for node 'ask' — it exited or was killed",
        "worker exited mid-corpus; this scenario never ran",
        "ModelProviderErrorish: a type that merely starts with the name",
    ):
        assert not is_dead_call(failure, cassette_miss="live", live_provider_present=True), failure


def test_a_worker_the_candidate_killed_is_not_a_dead_call() -> None:
    """`_failed` defaults to the replay mode, so the two places that report a
    WORKER's death rather than a MODEL's never mark one. Excluding those
    scenarios would hand `os._exit` back the acquittal ADR 0094 took away."""
    result = _failed("worker exited mid-corpus; this scenario never ran")
    assert result.failure is not None
    assert not result.dead_call


# --------------------------------------------------------------------------
# The runner: classification and the bounded retry
# --------------------------------------------------------------------------


class _Scripted(ModelProvider):
    name = "scripted"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="recorded", model="fake-1", input_tokens=4, output_tokens=2)


def _asking_graph() -> Graph:
    def ask(
        state: AEFState, ctx: object, services: Any
    ) -> tuple[StateDelta, str]:  # pragma: no cover - the worker runs the real one
        result = services.require_model_provider().complete(
            CompletionRequest(
                messages=(ProviderMessage(role="user", content=f"summarise: {state.objective}"),),
                model="",
            )
        )
        return (
            StateDelta(
                working_memory={"summary": result.content},
                plan=Plan(goal=state.objective, status="done"),
            ),
            END,
        )

    return Graph(
        id="asker",
        version="1",
        nodes={
            "ask": Node(
                id="ask",
                version="1",
                fn=ask,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: f"{s.run_id}:ask",
            )
        },
        edges=[],
        entry_node="ask",
    )


def _scenario_with_no_recording(sid: str) -> Scenario:
    """A scenario whose model call is NOT in the cassette — the shape a
    changed prompt has, and the only shape `--cassette-miss live` is for."""
    recorded = record_run(
        _asking_graph(),
        AEFState(run_id=sid, agent_id="a", objective=f"the {sid} passage"),
        agent_services(model_provider=_Scripted()),
        scenario_id=sid,
        recorded_at=RECORDED_AT,
    )
    payload = {k: v for k, v in recorded.to_payload().items() if k != "model_calls"}
    return Scenario.from_payload({**payload, "id": sid})


def _workspace(tmp_path: Path) -> Path:
    ws = Path(tempfile.mkdtemp(dir=tmp_path))
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")
    (ws / "agents" / "graph.py").write_text(ASKER_SOURCE)
    return ws


def _flaky_provider(root: Path, *, die_on: set[int]) -> dict[str, Any]:
    """A real `command` provider that exits non-zero on chosen invocations.

    The counter is a file, so the deaths are indexed by CALL rather than by
    scenario — which is what a transient provider failure actually looks
    like."""
    counter = root / "calls"
    counter.write_text("0")
    script = root / "flaky.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{counter}")\n'
        "n=$((n+1))\n"
        f'printf "%s" "$n" > "{counter}"\n'
        f'case "$n" in {"|".join(str(d) for d in sorted(die_on))}) '
        'echo "provider fell over" >&2; exit 7;; esac\n'
        'echo "a summary of the passage"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return {
        "impl": "command",
        "model": "stub-flaky",
        "fallback": [],
        "command": {
            "argv": [str(script), "{prompt}"],
            "isolation": ["no_tools", "single_turn"],
        },
    }


@pytest.mark.slow
def test_a_transient_death_is_retried_once_and_rescued(tmp_path: Path) -> None:
    """THE reproduction, and the fix.

    Before ADR 0185 this scenario came back `score=0.0000, cost_tokens=0` with
    a failure string nothing read, and G3 counted it as the candidate's score
    — reporting "1 previously-passing scenario(s) now score below 0.5" against
    a candidate that answered every scenario it was asked."""
    ws = _workspace(tmp_path)
    scenarios = [_scenario_with_no_recording(f"s{i}") for i in range(1, 5)]

    results = run_corpus_isolated(
        ws,
        scenarios,
        entrypoint="agents.graph:build_graph",
        cassette_miss="live",
        live_provider=_flaky_provider(tmp_path, die_on={3}),
    )

    assert results["s3"].retried, "the third call died and had to be retried"
    assert not results["s3"].dead_call, "the retry answered"
    assert results["s3"].failure is None
    assert results["s3"].score == 1.0
    # And the retry cost exactly one extra call, not a loop.
    assert (tmp_path / "calls").read_text() == "5"


@pytest.mark.slow
def test_a_death_that_repeats_is_excluded_not_scored_zero(tmp_path: Path) -> None:
    """Call 3 dies and so does its retry (call 4). One retry, then the
    scenario is declared dead — the bound is what stops a candidate that
    deterministically kills the provider from retrying forever."""
    ws = _workspace(tmp_path)
    scenarios = [_scenario_with_no_recording(f"s{i}") for i in range(1, 5)]

    results = run_corpus_isolated(
        ws,
        scenarios,
        entrypoint="agents.graph:build_graph",
        cassette_miss="live",
        live_provider=_flaky_provider(tmp_path, die_on={3, 4}),
    )

    assert results["s3"].dead_call and results["s3"].retried
    assert results["s3"].score == 0.0 and results["s3"].cost_tokens == 0
    assert "ModelProviderError" in (results["s3"].failure or "")
    assert [results[f"s{i}"].dead_call for i in (1, 2, 4)] == [False, False, False]
    assert (tmp_path / "calls").read_text() == "5", "one retry, then it stops"


@pytest.mark.slow
def test_a_replayed_run_classifies_no_dead_calls_at_all(tmp_path: Path) -> None:
    """The control. The same cassette misses under the DEFAULT
    `cassette_miss="fail"` are behavioural differences, scored 0 and counted —
    exactly as before ADR 0185."""
    ws = _workspace(tmp_path)
    scenarios = [_scenario_with_no_recording(f"s{i}") for i in range(1, 3)]

    results = run_corpus_isolated(
        ws, scenarios, entrypoint="agents.graph:build_graph", cassette_miss="fail"
    )

    assert all(r.score == 0.0 for r in results.values())
    assert all("ModelProviderError" in (r.failure or "") for r in results.values())
    assert not any(r.dead_call for r in results.values())
    assert not any(r.retried for r in results.values()), "nothing to retry on a replay"


def test_a_variant_run_reports_its_dead_and_rescued_scenarios() -> None:
    """The seam between the runner and `CohortBuilder`: `VariantRun` carries
    the two sets that become `CohortVerdict.dead_scenarios`."""
    from aef.harness.outcome import Outcome

    ok = Outcome(terminated=True, plan_status="done", error_count=0, policy_denials=0, node_path=())
    results: dict[str, ScenarioResult] = {
        "a": ScenarioResult(outcome=ok, score=1.0, cost_tokens=10),
        "b": ScenarioResult(
            outcome=ok, score=0.0, cost_tokens=0, failure="boom", dead_call=True, retried=True
        ),
        "c": ScenarioResult(outcome=ok, score=1.0, cost_tokens=10, retried=True),
    }
    run = VariantRun(
        label="candidate",
        outcomes={sid: r.outcome for sid, r in results.items()},
        scores=ScoreSet(
            label="candidate", per_scenario={sid: r.score for sid, r in results.items()}
        ),
        dead=frozenset(sid for sid, r in results.items() if r.dead_call),
        retried=frozenset(sid for sid, r in results.items() if r.retried),
    )
    assert run.dead == frozenset({"b"})
    assert run.retried == frozenset({"b", "c"})


def test_a_live_miss_with_NO_PROVIDER_is_not_a_dead_call() -> None:
    """ADR 0191's F1, the classification half.

    ADR 0185 gated `is_dead_call` on the MODE STRING alone, and a mode string
    is a request rather than a fact. `--cassette-miss live` with no `--config`
    builds no provider, so the cassette misses and raises

        NodeEvaluationError: ModelProviderError: cassette miss (...) and no
        live provider to fall through to

    — a `ModelProviderError` naming the ABSENCE of a provider, which the old
    rule read as a provider that died. Every scenario in the corpus was
    classified dead, retried, and then excluded from G3: on the reproduction's
    identical numbers, `G3 FAIL — 1 previously-passing scenario(s) now score
    below 0.5` counted became `G3 PASS — candidate mean 1 beats the control
    cohort's p95 of 0.9429` excluded.

    A miss with nothing behind it is a MISS. It is scored 0."""
    assert not is_dead_call(NO_PROVIDER_MISS, cassette_miss="live", live_provider_present=False)
    # The CONTROL: the same string with a provider present is still a death,
    # so this test is measuring the new condition and not the string.
    assert is_dead_call(NO_PROVIDER_MISS, cassette_miss="live", live_provider_present=True)


# ---------------------------------------------------------------------------
# What "bounded at one" actually bounds (ADR 0191's F7)
# ---------------------------------------------------------------------------

TWO_CALL_SOURCE = """
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.state import Plan, StateDelta


def _ask(services, text):
    return services.require_model_provider().complete(
        CompletionRequest(messages=(ProviderMessage(role="user", content=text),), model="")
    ).content


def ask(state, ctx, services):
    drafted = _ask(services, f"draft: {state.objective}")
    revised = _ask(services, f"revise: {state.objective}")
    return (
        StateDelta(
            working_memory={"summary": drafted + revised},
            plan=Plan(goal=state.objective, status="done"),
        ),
        END,
    )


def build_graph():
    return Graph(
        id="asker2", version="1",
        nodes={"ask": Node(id="ask", version="1", fn=ask, deterministic=False,
                           side_effects=SideEffect.EXTERNAL_CALL,
                           idempotency_key_fn=lambda s: f"{s.run_id}:ask")},
        edges=[], entry_node="ask",
    )
"""


def _two_call_scenario(sid: str) -> Scenario:
    """Recorded from the same source the worker will execute, then stripped of
    its `model_calls` — so both of the graph's calls miss the cassette."""
    namespace: dict[str, Any] = {}
    exec(compile(TWO_CALL_SOURCE, "<two_call>", "exec"), namespace)  # noqa: S102
    recorded = record_run(
        namespace["build_graph"](),
        AEFState(run_id=sid, agent_id="a", objective=f"the {sid} passage"),
        agent_services(model_provider=_Scripted()),
        scenario_id=sid,
        recorded_at=RECORDED_AT,
    )
    payload = {k: v for k, v in recorded.to_payload().items() if k != "model_calls"}
    return Scenario.from_payload({**payload, "id": sid})


@pytest.mark.slow
def test_the_retry_costs_one_extra_SCENARIO_not_one_extra_CALL(tmp_path: Path) -> None:
    """ADR 0185's consequences said "the retry costs at most one extra call
    per dead scenario". It does not, and the erratum is ADR 0191's F7.

    The retry re-runs the whole SCENARIO, and a scenario costs as many calls
    as its graph makes. Two scenarios of a two-call graph cost 4 calls clean;
    with the provider dying on call 4 — the second call of the second
    scenario — the run costs **6**. Two extra calls for one dead scenario.

    The true bound is one extra scenario EXECUTION: up to K extra calls for a
    K-call scenario, and at worst one extra full corpus pass. That is still
    bounded, which is what the retry needed to be; it is just not the number
    that was written down."""
    ws = Path(tempfile.mkdtemp(dir=tmp_path))
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")
    (ws / "agents" / "graph.py").write_text(TWO_CALL_SOURCE)

    results = run_corpus_isolated(
        ws,
        [_two_call_scenario("s1"), _two_call_scenario("s2")],
        entrypoint="agents.graph:build_graph",
        cassette_miss="live",
        live_provider=_flaky_provider(tmp_path, die_on={4}),
    )

    assert results["s2"].retried, "the fourth call died, so s2 was re-run"
    assert not results["s2"].dead_call, "the retry answered"
    calls = int((tmp_path / "calls").read_text())
    assert calls == 6, (
        f"a clean 2-scenario run of a 2-call graph costs 4 calls; this one cost {calls}. "
        f"The bound is one extra SCENARIO, not one extra call."
    )
    # The control that keeps the claim honest in the other direction: it is
    # still BOUNDED. One extra execution, never two.
    assert calls == 4 + 2
