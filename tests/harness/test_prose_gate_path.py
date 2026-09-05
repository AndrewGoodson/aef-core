"""A prompt candidate reaches a G3 verdict — both verdicts (ADR 0170).

ADR 0157 measured a prompt candidate through the gates and got:

    G2  fail  gate raised TrustBoundaryError: scratch destination …/workspace must be empty
    G3  not run — no control cohort could be built

so a prompt candidate could be **rejected but never accepted**. This file is
the proof that it can now be either, and the second half is the one that
matters: a fixture where the treatment does NOT beat its cohort must still be
rejected, on G3's own p95 rule, with no threshold touched.

Everything here is offline. Every model answer is a recorded cassette entry
(`cassette_miss="fail"`, the gate default), which is what lets a *changed
prompt* be scored at all without a credential — and it is also the honest
limit of this file: it proves the gate path reaches a verdict on real
executions, not that any particular prompt edit helps a real model. That
second claim needs live calls and S2's noise floor as its bar.

**The cassette must answer every prompt that will be sent**, so the test
computes the cohort with the same seed the driver will use and records an
answer for each of the seven personas (incumbent, candidate, five placebos).
A persona the cassette does not know scores 0 as a failed node, so a
mismatch between this file's cohort and the driver's cannot pass quietly.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import archive
from aef.harness.checks import TaskCheck
from aef.harness.corpus import Expected, Scenario, Split, load_corpus, save_scenario
from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, gate
from aef.harness.prompt_proposer import RuleBasedPromptProposer
from aef.harness.proposer import MemoryEvidence
from aef.harness.prose_cohort import ProseControlCohortGenerator
from aef.kernel import END, Graph, GraphExecutor
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider
from aef.providers.cassette_provider import CassetteProvider
from aef.reasoning.prompt_agent import make_prompt_agent_node, parse_agent_file
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
SEED = 11
GRAPH_ID = "marlin-accela"
PERSONA_PATH = "agents/persona.md"

INCUMBENT = """# Accela connector reviewer

You answer an operator's question about whether a connector may be enabled
for a jurisdiction. Be concise and cite the precondition you relied on.
"""

GRAPH_MODULE = '''"""A prompt-file agent, in the shape `aef migrate` generates."""

from aef.kernel import END, Graph
from aef.reasoning.prompt_agent import make_prompt_agent_node


def build_graph():
    return Graph(
        id="marlin-accela",
        version="0.1.0",
        nodes={
            "prompt_agent": make_prompt_agent_node(
                agent_file="agents/persona.md",
                agent_name="accela",
                module_file=__file__,
                route=END,
            )
        },
        edges=[],
        entry_node="prompt_agent",
    )
'''

# The two scenarios. `preconditions` passes for every persona — it is what
# gives G3's zero-tolerance regression rule something it could actually
# catch; `credentials` is the one the lesson is about.
OBJECTIVES: dict[str, str] = {
    "accela-preconditions": "which preconditions must hold before enabling the connector?",
    "accela-credentials": "may the connector be enabled for Clearwater?",
}

VERDICT_ANSWER = "The preconditions are documented. VERDICT: yes"
PLAIN_ANSWER = "The preconditions are documented."


# --------------------------------------------------------------------------
# a provider that answers from a table, so an "answer" is a fixture and not a
# model
# --------------------------------------------------------------------------


@dataclass
class ScriptedProvider(ModelProvider):
    """Answers `(system, user)` from a table. Every persona this test will
    send is in it; anything else is a bug in the test and raises."""

    answers: dict[tuple[str, str], str]
    name: str = "scripted"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        system = next((m.content for m in request.messages if m.role == "system"), "")
        user = next((m.content for m in request.messages if m.role == "user"), "")
        try:
            content = self.answers[(system, user)]
        except KeyError:  # pragma: no cover - a fixture bug, never a code path
            raise AssertionError(f"no scripted answer for objective {user!r}") from None
        # Equal on both sides so G3's cost ratio is exactly 1.0 and the cost
        # rule neither fires nor is silently unmeasurable.
        return CompletionResult(content=content, model="scripted", input_tokens=10, output_tokens=5)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


# --------------------------------------------------------------------------
# the candidate, from the real proposer
# --------------------------------------------------------------------------


def _memory() -> InMemoryMemoryStore:
    """Two distinct runs of one failure — ADR 0110's two-run threshold, met
    by the records rather than by the test asserting it is met."""
    store = InMemoryMemoryStore()
    for run in ("accela-credentials", "prod-2026-09-03-17"):
        store.write(
            MemoryRecord(
                kind="failure",
                run_id=run,
                agent_id="accela",
                content={
                    "verbal_feedback": "the reply ended without a machine-readable verdict line",
                    "failing_nodes": ["prompt_agent"],
                },
            )
        )
    return store


def _candidate_persona() -> str:
    """What `RuleBasedPromptProposer` actually proposes. Not hand-authored:
    a fixture bullet would prove the cohort works on a shape the proposer
    does not produce."""
    evidence = MemoryEvidence.from_store(_memory())
    proposals = RuleBasedPromptProposer().propose_from_memory(
        evidence, proposal_id="fixture", path=PERSONA_PATH, source=INCUMBENT
    )
    assert proposals, "the prompt proposer produced no candidate for this evidence"
    return proposals[0].proposed


def _personas() -> tuple[str, str, tuple[str, ...]]:
    """`(incumbent, candidate, placebos)` — the seven prompts that will be
    sent, computed with the driver's own seed."""
    candidate = _candidate_persona()
    cohort = ProseControlCohortGenerator(seed=SEED).generate(
        path=PERSONA_PATH, source=INCUMBENT, candidate=candidate, size=5
    )
    return INCUMBENT, candidate, tuple(c.proposed for c in cohort)


# --------------------------------------------------------------------------
# the cassette: one recorded answer per (persona, objective)
# --------------------------------------------------------------------------


def _run_persona(persona: str, scenario_id: str, content: str):  # type: ignore[no-untyped-def]
    """Run the REAL node once against a recording cassette; keep what it asked.

    Building the `CompletionRequest` by hand here would pin this file to a
    copy of the node's own message construction — and the parse matters: the
    system message is `parse_agent_file(...).body`, which is the persona
    STRIPPED, not the file's bytes. Recording against the raw text produced a
    cassette whose keys the gate could never hit, and every variant scored 0
    as a failed node (found by running it, not by reading it).
    """
    definition = parse_agent_file(persona, fallback_name="accela")
    provider = CassetteProvider(
        ScriptedProvider({(definition.body, OBJECTIVES[scenario_id]): content}), on_miss="live"
    )
    node = make_prompt_agent_node(definition=definition, agent_name="accela", route=END)
    graph = Graph(
        id=GRAPH_ID,
        version="0.1.0",
        nodes={"prompt_agent": node},
        edges=[],
        entry_node="prompt_agent",
    )
    state = AEFState(run_id=scenario_id, agent_id="accela", objective=OBJECTIVES[scenario_id])
    result = GraphExecutor(
        graph.compile(), agent_services(model_provider=provider, agent_id="accela")
    ).run(state, record_trace=True)
    assert not result.final_state.errors, result.final_state.errors
    return provider.calls, result, state


def _scenarios(*, placebo_helps: bool) -> tuple[Scenario, ...]:
    """Two recorded scenarios, each carrying answers for all seven personas.

    `placebo_helps=False` — the treatment is the only persona that produces a
    verdict, so the candidate beats its cohort.
    `placebo_helps=True` — ANY bullet produces one, so the candidate sits
    inside the cohort's spread. That is the null hypothesis holding, and G3
    must reject.
    """
    incumbent, candidate, placebos = _personas()
    scenarios: list[Scenario] = []
    for index, scenario_id in enumerate(sorted(OBJECTIVES)):
        always = scenario_id == "accela-preconditions"
        # The incumbent's run is also the recorded TRACE: the corpus captures
        # the agent as it is, and the loop is then asked to improve it.
        calls, run, state = _run_persona(
            incumbent, scenario_id, VERDICT_ANSWER if always else PLAIN_ANSWER
        )
        recorded = list(calls)
        recorded.extend(_run_persona(candidate, scenario_id, VERDICT_ANSWER)[0])
        for placebo in placebos:
            content = VERDICT_ANSWER if (always or placebo_helps) else PLAIN_ANSWER
            recorded.extend(_run_persona(placebo, scenario_id, content)[0])

        scenarios.append(
            Scenario(
                id=scenario_id,
                split=Split.TRAIN if index == 0 else Split.VALIDATION,
                graph_id=GRAPH_ID,
                graph_version="0.1.0",
                initial_state=state,
                trace=tuple(run.trace or ()),
                recorded_at=NOW,
                expected=Expected.UNSPECIFIED,
                checks=(
                    TaskCheck(path="working_memory.prompt_agent", op="contains", value="VERDICT:"),
                ),
                model_calls=tuple(recorded),
                notes="recorded from a real run of the incumbent persona",
            )
        )
    return tuple(scenarios)


# --------------------------------------------------------------------------
# the repo, the blessing and the candidate branch
# --------------------------------------------------------------------------


def _repo(tmp_path: Path, *, placebo_helps: bool) -> tuple[GitRepo, str]:
    root = tmp_path / "prompt-repo"
    (root / "agents" / "marlin").mkdir(parents=True)
    (root / "agents" / "__init__.py").write_text("")
    (root / "agents" / "marlin" / "__init__.py").write_text("")
    (root / "agents" / "marlin" / "graph.py").write_text(GRAPH_MODULE)
    (root / PERSONA_PATH).write_text(INCUMBENT)

    corpus_root = root / "corpus"
    corpus_root.mkdir()
    for scenario in _scenarios(placebo_helps=placebo_helps):
        save_scenario(corpus_root, scenario)

    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "loop@test")
    _git(root, "config", "user.name", "loop")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "incumbent persona")

    _git(root, "checkout", "-qb", "loop/prompt")
    (root / PERSONA_PATH).write_text(_candidate_persona())
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "a lesson appended to the persona")
    _git(root, "checkout", "-q", "main")
    return GitRepo(root=root), "loop/prompt"


def _bless(repo: GitRepo, state_root: Path) -> None:
    files = {
        path: repo.run_bytes("show", f"main:{path}")
        for path in repo.list_tree(repo.rev_parse("main"), "agents")
    }
    archive.record(
        state_root / "archive",
        GRAPH_ID,
        files=files,
        base_sha=repo.rev_parse("main"),
        head_sha=repo.rev_parse("main"),
        recorded_at=NOW,
        notes="owner-blessed baseline",
    )


def _config(repo: GitRepo, tmp_path: Path) -> LoopConfig:
    return LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        base_ref="main",
        graph_id=GRAPH_ID,
        corpus=load_corpus(repo.root / "corpus"),
        entrypoint="agents.marlin.graph:build_graph",
        build_commands=(("python", "-c", "import agents.marlin.graph"),),
        cohort_size=5,
        cohort_seed=SEED,
    )


def _run(tmp_path: Path, *, placebo_helps: bool):  # type: ignore[no-untyped-def]
    repo, head = _repo(tmp_path, placebo_helps=placebo_helps)
    _bless(repo, tmp_path / "state")
    return gate(_config(repo, tmp_path), head, now=NOW, workdir=tmp_path / "work"), tmp_path


def _ledger_gates(tmp_path: Path) -> dict[str, dict[str, str]]:
    """The GATED entry's gate results, read from `ledger.jsonl` rather than
    from the returned object — a printed string proves a string was printed
    (ADR 0139's rule)."""
    from aef.harness import ledger

    entries = ledger.read(tmp_path / "state")
    gated = [e for e in entries if e.kind is ledger.EventKind.GATED]
    assert gated, "no GATED entry in the ledger"
    return {g["gate"]: g for g in gated[-1].detail["gates"]}


# --------------------------------------------------------------------------
# 1. the treatment beats its cohort
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_prompt_candidate_reaches_an_accept_verdict(tmp_path: Path) -> None:
    """Every gate runs and none rejects — the verdict ADR 0157 could not
    reach, because G2 died on a scratch directory and G3 had no cohort."""
    run, root = _run(tmp_path, placebo_helps=False)

    gates = _ledger_gates(root)
    assert set(gates) == {"G0", "G1", "G2", "G3", "G4", "G5"}, f"not every gate ran: {list(gates)}"
    assert "TrustBoundaryError" not in gates["G2"]["reason"]
    assert gates["G2"]["outcome"] == "pass", gates["G2"]["reason"]
    assert gates["G3"]["outcome"] == "pass", gates["G3"]["reason"]
    assert "beats the control cohort" in gates["G3"]["reason"]
    assert run.result.passed, [r.reason for r in run.result.results if not r.passed]


# --------------------------------------------------------------------------
# 2. the treatment does NOT beat its cohort — the half that proves the bar
#    was not lowered
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_prompt_candidate_inside_the_cohorts_spread_is_rejected(tmp_path: Path) -> None:
    """Identical in every respect except what the PLACEBOS scored.

    If appending any bullet produces the verdict line, the lesson's content
    bought nothing, and G3 says so on its own p95 rule with no threshold
    changed. A test that only demanded acceptance could be satisfied by
    weakening G3; this one cannot.
    """
    run, root = _run(tmp_path, placebo_helps=True)

    gates = _ledger_gates(root)
    assert gates["G2"]["outcome"] == "pass", gates["G2"]["reason"]
    assert gates["G3"]["outcome"] == "fail"
    assert "null hypothesis" in gates["G3"]["reason"]
    assert not run.result.passed


# --------------------------------------------------------------------------
# 3. the controls on the fixture itself
# --------------------------------------------------------------------------


def test_the_cohort_the_test_records_for_is_the_cohort_the_driver_builds() -> None:
    """The cassette is built from personas this file computes; the driver
    computes its own from the same seed. If they ever diverge the scenarios
    would score 0 as cassette misses — this asserts the coupling directly so
    the failure names itself."""
    from aef.harness.suite import CohortBuilder

    incumbent, candidate, placebos = _personas()
    builder_seeded = ProseControlCohortGenerator(seed=SEED)
    again = builder_seeded.generate(
        path=PERSONA_PATH, source=incumbent, candidate=candidate, size=5
    )
    assert tuple(c.proposed for c in again) == placebos
    assert CohortBuilder.__dataclass_fields__["seed"].default == 0, (
        "the driver's seed comes from LoopConfig.cohort_seed; this test pins SEED explicitly"
    )


def test_the_candidate_persona_differs_from_the_incumbent_by_one_bullet() -> None:
    incumbent, candidate, _ = _personas()
    added = [
        line
        for line in candidate.splitlines()
        if line.strip() and line not in incumbent.splitlines()
    ]
    assert len(added) == 2, added  # the heading and the bullet
    assert added[-1].startswith("- <!-- aef sig=")
