"""Milestone 2: the config fields that validated and were read by nothing.

`domain_gates` has been a declared injection point since Phase 0 with no
production caller — the shape ADR 0092 named as indistinguishable from a
missing feature. These tests send something down the wire rather than
asserting the wiring exists: a real suite module on disk, resolved through a
real `aef.yaml`, applied to a real run.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from aef.config import DomainGateError, build_domain_gates, load_agent_config
from aef.config.schema import EvaluatorConfig
from aef.state import AEFState

SUITE_MODULE = """
def always_true(state):
    return True


def always_false(state):
    return False


def objective_is_not_empty(state):
    return bool(state.objective.strip())


NOT_CALLABLE = 3
"""

CONFIG = """
model_provider:
  impl: anthropic
  model: claude-sonnet

memory:
  impl: in_memory

evaluator:
  suites: {suites}

objectives: "score a run against the owner's own gates"
"""


@pytest.fixture
def suite_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "suites.py").write_text(SUITE_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def _config(tmp_path: Path, suites: str) -> Path:
    path = tmp_path / "aef.yaml"
    path.write_text(CONFIG.format(suites=suites))
    return path


def _state() -> AEFState:
    return AEFState(run_id="r", agent_id="a", objective="do the thing")


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def test_a_suite_resolves_to_the_callable_it_names(suite_repo: Path) -> None:
    gates = build_domain_gates(EvaluatorConfig(suites=["suites:always_true"]))
    assert list(gates) == ["suites:always_true"]
    assert gates["suites:always_true"](_state()) is True


def test_a_bare_name_is_refused_with_the_shape_it_should_have_had() -> None:
    """A bare name needs a registry someone registered into, which needs an
    import to have already happened — invisible and order-dependent."""
    with pytest.raises(DomainGateError, match="module:function"):
        build_domain_gates(EvaluatorConfig(suites=["private_azure_pentest"]))


def test_an_unimportable_module_is_refused_not_skipped() -> None:
    """Replacing 'ignored because unwired' with 'ignored because
    unresolvable' would be no improvement at all."""
    with pytest.raises(DomainGateError, match="cannot import"):
        build_domain_gates(EvaluatorConfig(suites=["no_such_module_anywhere:gate"]))


def test_a_missing_attribute_is_refused(suite_repo: Path) -> None:
    with pytest.raises(DomainGateError, match="has no attribute"):
        build_domain_gates(EvaluatorConfig(suites=["suites:not_defined"]))


def test_a_non_callable_attribute_is_refused(suite_repo: Path) -> None:
    with pytest.raises(DomainGateError, match="not callable"):
        build_domain_gates(EvaluatorConfig(suites=["suites:NOT_CALLABLE"]))


def test_a_duplicate_suite_is_refused(suite_repo: Path) -> None:
    """A duplicate collapses to one gate, so the count an owner reads is
    wrong while every gate still 'passes'."""
    with pytest.raises(DomainGateError, match="twice"):
        build_domain_gates(EvaluatorConfig(suites=["suites:always_true", "suites:always_true"]))


# --------------------------------------------------------------------------
# The gates reach a score
# --------------------------------------------------------------------------


def test_a_failing_suite_fails_the_run(suite_repo: Path, tmp_path: Path) -> None:
    """The behaviour, not the wiring: a run that the rule-based evaluator
    alone would pass must FAIL once the owner's gate says no."""
    from aef.cli.eval import build_evaluator
    from aef.state import Plan

    state = _state()
    state.plan = Plan(goal="do the thing", status="done")

    assert build_evaluator(_config(tmp_path, "[]")).evaluate(state).passed, (
        "the control is wrong: this run must pass without any domain gate"
    )

    record = build_evaluator(_config(tmp_path, '["suites:always_false"]')).evaluate(state)
    assert record.domain_gates == {"suites:always_false": False}
    assert not record.passed


def test_a_passing_suite_leaves_the_verdict_alone(suite_repo: Path, tmp_path: Path) -> None:
    from aef.cli.eval import build_evaluator
    from aef.state import Plan

    state = _state()
    state.plan = Plan(goal="do the thing", status="done")
    record = build_evaluator(_config(tmp_path, '["suites:always_true"]')).evaluate(state)
    assert record.domain_gates == {"suites:always_true": True}
    assert record.passed


def test_a_domain_gate_can_never_rescue_a_failing_run(suite_repo: Path, tmp_path: Path) -> None:
    """`passed` is `task_completion >= 0.5 AND all(domain_gates)`, so a gate
    can only ever make the verdict stricter. That is what makes wiring this
    safe without touching `task_completion` semantics (ADR 0038)."""
    from aef.cli.eval import build_evaluator

    state = _state()
    state.errors.append({"node_id": "n", "message": "boom"})
    record = build_evaluator(_config(tmp_path, '["suites:always_true"]')).evaluate(state)
    assert record.task_completion == 0.0
    assert record.domain_gates == {"suites:always_true": True}
    assert not record.passed, "a passing domain gate rescued a failing run"


def test_the_gate_sees_the_real_state(suite_repo: Path, tmp_path: Path) -> None:
    """A gate handed a placeholder would pass every planted fault."""
    from aef.cli.eval import build_evaluator

    config = _config(tmp_path, '["suites:objective_is_not_empty"]')
    populated = build_evaluator(config).evaluate(_state())
    assert populated.domain_gates == {"suites:objective_is_not_empty": True}

    blank = _state()
    blank.objective = "   "
    assert build_evaluator(config).evaluate(blank).domain_gates == {
        "suites:objective_is_not_empty": False
    }


# --------------------------------------------------------------------------
# objectives, and the two refusals
# --------------------------------------------------------------------------


def test_objectives_is_the_default_objective(tmp_path: Path) -> None:
    """Two things with one name and no connection: the field was required,
    validated and never read while `--objective` was required on every
    invocation (ADR 0092, ADR 0100)."""
    import argparse

    from aef.cli.main import _resolve_objective

    config = _config(tmp_path, "[]")
    args = argparse.Namespace(objective=None, config=str(config))
    assert _resolve_objective(args) == "score a run against the owner's own gates"

    args.objective = "an explicit override"
    assert _resolve_objective(args) == "an explicit override", "the flag must still win"


def test_neither_an_objective_nor_a_config_is_an_error() -> None:
    """An empty objective would be scored against nothing."""
    import argparse

    from aef.cli.main import _resolve_objective

    with pytest.raises(SystemExit, match="no objective"):
        _resolve_objective(argparse.Namespace(objective=None, config=None))


def test_a_knowledge_graph_block_is_refused_at_load_time(tmp_path: Path) -> None:
    """Nothing builds one, so validating the block would let an owner believe
    their agent had a knowledge graph the runtime never gave it."""
    path = tmp_path / "kg.yaml"
    path.write_text(
        CONFIG.format(suites="[]") + "\nknowledge_graph:\n  impl: neo4j\n  ontology: x.ttl\n"
    )
    with pytest.raises(Exception, match="builder that does not exist"):
        load_agent_config(path)


def test_the_shipped_example_configs_still_load() -> None:
    """Both shipped examples declared `impl: neo4j`, and the refusal caught
    them. A validator whose own examples cannot load is a validator nobody
    will keep."""
    config_dir = Path(__file__).resolve().parents[2] / "aef" / "config"
    for name in ("agent.example.yaml", "agent.azure_sec.yaml"):
        load_agent_config(config_dir / name)


def test_the_generated_stub_no_longer_claims_these_are_ignored() -> None:
    """2d: if the STILL NOT WIRED section did not shrink, the milestone did
    not happen. Asserted against the rendered stub, not the source."""
    from aef.cli.adopt import render_aef_yaml

    stub = render_aef_yaml("demo")
    assert "STILL NOT WIRED" not in stub
    assert "`objectives` is NOT the objective a run uses" not in stub
    assert "`evaluator.suites` is read by nothing" not in stub
    assert "REFUSED" in stub


def test_the_generated_stub_still_loads(tmp_path: Path) -> None:
    """The stub tells an adopter to fill in `evaluator.suites`; a stub that
    does not itself load would fail them on their first command."""
    from aef.cli.adopt import render_aef_yaml

    path = tmp_path / "aef.yaml"
    path.write_text(render_aef_yaml("demo"))
    config = load_agent_config(path)
    assert config.evaluator.suites == []
    assert config.knowledge_graph is None


def test_eval_accepts_a_config_flag() -> None:
    """The flag `aef eval` needs to apply the owner's suites at all."""
    result = subprocess.run(
        [sys.executable, "-m", "aef.cli.main", "eval", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--config" in result.stdout


# --------------------------------------------------------------------------
# The adversarial round for this milestone. Every one REPRODUCED first.
# --------------------------------------------------------------------------


def test_a_suite_may_not_name_the_judging_apparatus() -> None:
    """A suite is arbitrary code the config points at and the evaluator calls.
    G0 forbids agent code importing `aef.harness`/`aef.cli`; without this,
    `evaluator.suites` was a second door into the same rooms. Reproduced:
    `aef.harness.loop:gate` resolved cleanly.

    The forbidden list is READ FROM G0, so this asserts against the gate's own
    constant rather than a copy that would drift (ADR 0091).
    """
    from aef.harness.gates.g0_static_safety import FORBIDDEN_AEF_SUBPACKAGES

    assert FORBIDDEN_AEF_SUBPACKAGES, "the control is empty; this test proves nothing"
    for forbidden in FORBIDDEN_AEF_SUBPACKAGES:
        with pytest.raises(DomainGateError, match="judging apparatus"):
            build_domain_gates(EvaluatorConfig(suites=[f"{forbidden}.anything:gate"]))
        with pytest.raises(DomainGateError, match="judging apparatus"):
            build_domain_gates(EvaluatorConfig(suites=[f"{forbidden}:gate"]))


def test_a_prefix_that_merely_looks_like_a_forbidden_package_is_allowed(
    suite_repo: Path,
) -> None:
    """`aef.harnessing` is not `aef.harness`. A `startswith` without the dot
    would reject an adopter's unrelated package for sharing a prefix."""
    (suite_repo / "aef_harnessed.py").write_text("def gate(state):\n    return True\n")
    gates = build_domain_gates(EvaluatorConfig(suites=["aef_harnessed:gate"]))
    assert gates["aef_harnessed:gate"](_state()) is True


def test_a_gate_that_does_not_return_a_bool_is_refused(suite_repo: Path) -> None:
    """REPRODUCED: a gate returning `"yes"` landed in `domain_gates` — typed
    `dict[str, bool]` — as `'yes'`, and `passed` read it truthily. So any
    non-empty string passed and `""` or `0` failed, silently."""
    (suite_repo / "verdicts.py").write_text(
        "def yes(state):\n    return 'yes'\n\n\n"
        "def forgot(state):\n    pass\n\n\n"
        "def zero(state):\n    return 0\n"
    )
    for name in ("yes", "forgot", "zero"):
        gate = build_domain_gates(EvaluatorConfig(suites=[f"verdicts:{name}"]))[f"verdicts:{name}"]
        with pytest.raises(DomainGateError, match="not a bool"):
            gate(_state())


def test_a_gate_that_raises_names_itself(suite_repo: Path) -> None:
    """A raw traceback from someone else's module does not say which suite
    produced it, and an owner reading it blames the evaluator."""
    (suite_repo / "boom.py").write_text("def gate(state):\n    raise ValueError('inner')\n")
    gate = build_domain_gates(EvaluatorConfig(suites=["boom:gate"]))["boom:gate"]
    with pytest.raises(DomainGateError, match="boom:gate.*ValueError.*inner"):
        gate(_state())


def test_resolving_a_suite_executes_its_module_body(suite_repo: Path) -> None:
    """Documented, not fixed. `module:function` resolution imports, and an
    import runs the module body — the same property `--entrypoint` has had
    since the loop was built. Containing it needs the sandbox Milestone 4
    addresses; pinning it here so the property is a known one rather than a
    surprise found later.
    """
    (suite_repo / "noisy.py").write_text(
        "RAN = []\nRAN.append('body')\n\n\ndef gate(state):\n    return True\n"
    )
    build_domain_gates(EvaluatorConfig(suites=["noisy:gate"]))
    import noisy  # type: ignore[import-not-found]

    assert noisy.RAN == ["body"], "resolution did not import — this test is not testing it"
