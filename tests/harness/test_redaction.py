"""Redaction at the harvest boundary (ADR 0119). Planted secrets go in; the
corpus on disk is scanned afterwards — the detector is proved against the
fault every run, not once at authoring."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aef.harness.corpus import load_corpus
from aef.harness.harvest import RecordedRun, harvest, save_run
from aef.harness.redaction import DEFAULT_PATTERNS, RedactionError, RedactionPolicy
from aef.kernel import END, Context, Graph, GraphExecutor, Node, Route, Services
from aef.state import AEFState, Plan, StateDelta

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
EMAIL = "jane.doe@tenant-corp.example"
TOKEN = "sk-live-4f8a9b2c1d0e7f6a5b4c3d2e1f0a9b8c"
BEARER = "Bearer eyJhbGciOiJIUzI1NiJ9.dGVuYW50LXNlY3JldA.abc123"


def _graph(*, branch_on_token: bool = False, leak_env: bool = False) -> Graph:
    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        if branch_on_token and state.working_memory.get("token") == TOKEN:
            # Behaviour depends on the secret: fails only when it is present.
            return StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[{"node_id": ctx.node_id, "error": "auth rejected"}],
            ), END
        if leak_env:
            # A secret the input redaction cannot reach.
            return StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[{"node_id": ctx.node_id, "error": f"upstream said {TOKEN}"}],
            ), END
        if state.working_memory.get("fail"):
            return StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[{"node_id": ctx.node_id, "error": f"boom for {state.objective}"}],
            ), END
        return StateDelta(plan=Plan(goal=state.objective, status="done")), END

    node = Node(id="work", version="0.1.0", fn=work, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"work": node}, edges=[], entry_node="work")


def _record(
    runs: Path, graph: Graph, run_id: str, *, objective: str, wm: dict[str, object]
) -> None:
    state = AEFState(run_id=run_id, agent_id="demo", objective=objective, working_memory=wm)
    ticks = iter([NOW + timedelta(seconds=i) for i in range(20)])
    result = GraphExecutor(graph.compile(), Services(clock=lambda: next(ticks))).run(
        state, record_trace=True
    )
    assert result.trace is not None
    save_run(
        runs,
        RecordedRun(
            run_id=run_id,
            graph_id=graph.id,
            graph_version=graph.version,
            initial_state=state,
            trace=result.trace,
            at=NOW,
        ),
    )


def _corpus_text(root: Path) -> str:
    return "\n".join(p.read_text() for p in root.rglob("*.json"))


# ---------------------------------------------------------------------------
# The policy on its own
# ---------------------------------------------------------------------------
def test_default_patterns_catch_the_planted_secrets() -> None:
    policy = RedactionPolicy()
    text, n = policy.redact_text(f"contact {EMAIL}, key {TOKEN}, header {BEARER}")
    assert n == 3
    assert EMAIL not in text and TOKEN not in text and "eyJhbGci" not in text
    assert "[REDACTED:email]" in text and "[REDACTED:api_key]" in text
    assert policy.find({"a": [text]}) == ()


def test_redact_state_drops_secret_keys_and_scrubs_nested_text() -> None:
    state = AEFState(
        run_id="r",
        agent_id="a",
        objective=f"email {EMAIL} about the invoice",
        working_memory={"token": TOKEN, "note": {"cc": [EMAIL]}, "fail": True},
    )
    redacted, n = RedactionPolicy().redact_state(state)
    assert "token" not in redacted.working_memory
    assert redacted.working_memory["fail"] is True
    assert EMAIL not in redacted.objective
    assert redacted.working_memory["note"]["cc"] == ["[REDACTED:email]"]
    assert n == 3  # email in objective, email in note, dropped key


def test_a_bad_pattern_is_refused_at_construction() -> None:
    with pytest.raises(RedactionError, match="does not compile"):
        RedactionPolicy(patterns=(("broken", "("),))


def test_default_patterns_do_not_eat_ordinary_text() -> None:
    text, n = RedactionPolicy().redact_text("settle the invoice for order 12345 by Friday")
    assert n == 0 and "invoice" in text


# ---------------------------------------------------------------------------
# Through harvest
# ---------------------------------------------------------------------------
def test_a_harvested_run_is_redacted_and_still_fails_the_same_way(tmp_path: Path) -> None:
    graph = _graph()
    _record(
        tmp_path / "runs",
        graph,
        "r1",
        objective=f"email {EMAIL} the report",
        wm={"fail": True, "token": TOKEN},
    )
    outcome = harvest(tmp_path / "runs", tmp_path / "corpus", graph, now=NOW + timedelta(hours=1))
    assert outcome.promoted == ("r1",), outcome.lines
    assert outcome.redactions == 2
    text = _corpus_text(tmp_path / "corpus")
    for secret in (EMAIL, TOKEN):
        assert secret not in text, f"{secret!r} reached the corpus on disk"
    scenario = load_corpus(tmp_path / "corpus").scenarios[0]
    assert "token" not in scenario.initial_state.working_memory
    assert "[REDACTED:email]" in scenario.initial_state.objective
    assert "2 redaction(s) applied" in scenario.notes
    # The stored trace is the RE-EXECUTED one on redacted input: it carries
    # the redacted objective, not the original error text.
    final = scenario.initial_state
    for record in scenario.trace:
        final = record.delta.apply(final)
    assert final.errors and EMAIL not in final.errors[0]["error"]


def test_a_run_whose_behaviour_depends_on_the_secret_is_rejected(tmp_path: Path) -> None:
    graph = _graph(branch_on_token=True)
    _record(tmp_path / "runs", graph, "r1", objective="task", wm={"token": TOKEN})
    outcome = harvest(tmp_path / "runs", tmp_path / "corpus", graph, now=NOW + timedelta(hours=1))
    assert outcome.promoted == ()
    assert outcome.rejected_redaction_changed_behaviour == ("r1",)
    assert not (tmp_path / "corpus").exists() or TOKEN not in _corpus_text(tmp_path / "corpus")


def test_a_secret_the_graph_reintroduces_is_caught_by_the_output_scan(tmp_path: Path) -> None:
    graph = _graph(leak_env=True)
    _record(tmp_path / "runs", graph, "r1", objective="task", wm={"fail": True, "note": EMAIL})
    outcome = harvest(tmp_path / "runs", tmp_path / "corpus", graph, now=NOW + timedelta(hours=1))
    assert outcome.promoted == ()
    assert outcome.rejected_unredactable == ("r1",)
    assert (
        TOKEN not in _corpus_text(tmp_path / "corpus") if (tmp_path / "corpus").exists() else True
    )


def test_redaction_off_is_explicit_and_writes_the_raw_run(tmp_path: Path) -> None:
    """The control for the detector: with the policy disabled the planted
    secret DOES reach disk, so the scan in the tests above is a real scan."""
    graph = _graph()
    _record(tmp_path / "runs", graph, "r1", objective=f"email {EMAIL}", wm={"fail": True})
    outcome = harvest(
        tmp_path / "runs", tmp_path / "corpus", graph, now=NOW + timedelta(hours=1), redaction=None
    )
    assert outcome.promoted == ("r1",)
    assert EMAIL in _corpus_text(tmp_path / "corpus")


def test_a_run_with_nothing_to_redact_is_stored_with_its_original_trace(tmp_path: Path) -> None:
    graph = _graph()
    _record(tmp_path / "runs", graph, "r1", objective="plain task", wm={"fail": True})
    outcome = harvest(tmp_path / "runs", tmp_path / "corpus", graph, now=NOW + timedelta(hours=1))
    assert outcome.promoted == ("r1",) and outcome.redactions == 0
    assert "redaction(s)" not in load_corpus(tmp_path / "corpus").scenarios[0].notes


def test_every_default_pattern_is_exercised() -> None:
    """A pattern nobody has a sample for is a pattern nobody knows works."""
    samples = {
        "email": EMAIL,
        "api_key": TOKEN,
        "bearer": BEARER,
        "aws_key": "AKIAIOSFODNN7EXAMPLE",
        # Was `"A" * 44`, which the corrected `opaque_secret` no longer
        # matches: 40+ chars is not on its own a secret (ADR 0126).
        "opaque_secret": "a1B2c3D4" * 5 + "xyz9",
    }
    for label, pattern in DEFAULT_PATTERNS:
        assert re.search(pattern, samples[label]), label


def test_a_hyphenated_english_objective_is_not_a_secret() -> None:
    """Reproduced against the real policy: this objective was redacted and the
    harvested scenario admitted with a placeholder, which is a scenario that
    no longer tests what the run did (ADR 0126)."""
    slug = "migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime"
    # The second slug leads with a segment carrying both a letter and a
    # numeral, so only excluding the hyphen itself keeps it out of the match.
    versioned = "v2-migrate-the-customer-billing-pipeline-with-zero-downtime"
    for text in (slug, versioned):
        assert len(text) >= 40
        assert RedactionPolicy().find({"objective": text}) == (), text
        state = AEFState(run_id="r1", agent_id="a1", objective=text)
        assert RedactionPolicy().redact_state(state)[0].objective == text
    # Nor is a long snake_case identifier, the other shape 40+ chars catches.
    ident = "test_a_downstream_node_counts_as_a_recurrence_of_its_own_lesson"
    assert RedactionPolicy().find({"note": ident}) == ()


def test_a_long_mixed_token_is_still_a_secret() -> None:
    """The control the previous test must not weaken: 44 chars carrying both
    letters and numerals, with no prefix any other pattern anchors on."""
    token = "a1B2c3D4" * 5 + "xyz9"
    assert len(token) == 44
    assert RedactionPolicy().find({"objective": token}) == ("opaque_secret",)
    state = AEFState(run_id="r1", agent_id="a1", objective=token)
    redacted, hits = RedactionPolicy().redact_state(state)
    assert redacted.objective == "[REDACTED:opaque_secret]" and hits == 1
    # Base64 payloads keep matching too.
    b64 = "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNlY3JldCB0b2tlbjEyMw=="
    assert RedactionPolicy().find({"objective": b64}) == ("opaque_secret",)
