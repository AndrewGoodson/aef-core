"""Live model calls inside the gates: the opt-in, and the provider that crosses.

ADR 0158 found two HIGH defects that together meant **no provider served a
live cassette miss inside the gates**, on any repo — so `UPGRADE_LOOP.md`'s
rule ("a prompt candidate is gated live, or not at all") resolved to the
second every time:

  * **F-M5-3** — `sandbox.DEFAULT_ENV_ALLOWLIST` carries no `USER`, so
    `claude -p` answers `Not logged in` inside the gates' worker. That is the
    allowlist *working*: it exists so no credential is inherited by the one
    process that runs candidate code. The fix is therefore an owner decision
    rather than a one-word patch — `gates.live_model_calls`, off by default.
  * **F-M5-2** — only `{impl, model}` crossed the worker boundary, so
    `impl: command` (the one provider needing no credential at all) could not
    be rebuilt worker-side and every scenario failed as `worker refused
    configuration`, which G2 reported as a behavioural regression.

Both closed in ADR 0181. These tests are the regressions; the two strict
xfails in `tests/cli/test_prompt_repo_acceptance.py` are the same two
findings pinned at the surface where they were found.

No test here makes a live model call. The `command` provider is `/bin/echo`,
which is a real subprocess through the real `CommandProvider` — configuration
rather than a mock, the substitution ADR 0158's offline half already uses.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.config.loader import load_agent_config_text
from aef.config.schema import GatesConfig, ModelProviderConfig
from aef.harness.corpus import Scenario
from aef.harness.git import GitRepo
from aef.harness.isolated_suite import run_corpus_isolated
from aef.harness.loop import (
    LiveGatingDisabledError,
    LoopConfig,
    LoopPaths,
    PolicyConfigError,
    _live_model_calls,
    _live_provider_from_base_ref,
    _worker_sandbox_policy,
)
from aef.harness.recorder import record_run
from aef.harness.sandbox import (
    DEFAULT_ENV_ALLOWLIST,
    HARNESS_LOGIN_ENV,
    NetworkPolicy,
    SandboxPolicy,
    scrubbed_env,
    with_harness_login,
)
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderMessage,
)
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

RECORDED_AT = datetime(2026, 9, 5, tzinfo=UTC)

# `impl: command` with `/bin/echo` — a real subprocess, a real provider, and
# no credential anywhere. This is the config F-M5-2 could not rebuild.
COMMAND_YAML = """extends: _base
model_provider:
  impl: command
  model: stub-echo
  fallback: []
  command:
    argv: ["/bin/echo", "{system}", "{prompt}"]
    system_argv: ["{system}"]
    isolation: ["no_tools", "single_turn"]
memory: {impl: in_memory}
evaluator: {suites: []}
tools: {allow: []}
policies: {require_hitl_above_risk: 0.0, forbid: []}
objectives: "echo the question back"
evolution: {enabled: false}
"""

LOGIN_YAML = """extends: _base
model_provider: {impl: claude_code, model: claude-opus-5, fallback: []}
memory: {impl: in_memory}
evaluator: {suites: []}
tools: {allow: []}
policies: {require_hitl_above_risk: 0.0, forbid: []}
objectives: "answer the question"
evolution: {enabled: false}
"""

OPTED_IN = "gates: {live_model_calls: true}\n"


def _repo(tmp_path: Path, yaml_text: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, capture_output=True
    )
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    (repo / "aef.yaml").write_text(yaml_text)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "init"], check=True, capture_output=True
    )
    return repo


def _config(repo: Path, tmp_path: Path, *, cassette_miss: str = "live") -> LoopConfig:
    return LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state"),
        config_path="aef.yaml",
        cassette_miss=cassette_miss,
    )


# ---------------------------------------------------------------------------
# F-M5-3, one half: the control the default still enforces
# ---------------------------------------------------------------------------


def test_the_default_allowlist_still_inherits_no_login() -> None:
    """The containment property, pinned so the fix cannot quietly become the
    default. `HARNESS_LOGIN_ENV` is a widening an owner asks for; a
    `DEFAULT_ENV_ALLOWLIST` that already carried it would mean every gate
    pass on every repo could spend the operator's quota."""
    assert not (DEFAULT_ENV_ALLOWLIST & HARNESS_LOGIN_ENV)
    assert "USER" not in DEFAULT_ENV_ALLOWLIST
    # `LOGNAME` is the other conventional spelling of the same fact and was
    # measured NOT to substitute (ADR 0181); it is in neither set.
    assert "LOGNAME" not in DEFAULT_ENV_ALLOWLIST | HARNESS_LOGIN_ENV


def test_the_widening_is_exactly_the_variable_that_was_measured() -> None:
    """One variable, because that is what the probe found. A widening that
    grew by convenience would be inheriting credentials nobody measured a
    need for."""
    assert HARNESS_LOGIN_ENV == frozenset({"USER"})
    base = SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)
    widened = with_harness_login(base)
    assert widened.env_allowlist - base.env_allowlist == HARNESS_LOGIN_ENV
    # `SandboxPolicy` is frozen and `with_harness_login` returns a copy: no
    # caller's policy becomes credential-carrying behind its back.
    assert "USER" not in base.env_allowlist


def test_the_child_environment_carries_the_login_only_once_widened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end the worker actually sees. `scrubbed_env` is what
    `NodeWorkerSession` hands to `Popen`, so this is the variable's whole
    journey from the operator's shell to the candidate's process."""
    monkeypatch.setenv("USER", "the-operator")
    base = SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)
    assert "USER" not in scrubbed_env(base)
    assert scrubbed_env(with_harness_login(base))["USER"] == "the-operator"


# ---------------------------------------------------------------------------
# The opt-in
# ---------------------------------------------------------------------------


def test_live_model_calls_are_off_unless_the_repo_says_otherwise() -> None:
    assert GatesConfig().live_model_calls is False
    assert load_agent_config_text(LOGIN_YAML, source="t").gates.live_model_calls is False
    assert load_agent_config_text(LOGIN_YAML + OPTED_IN, source="t").gates.live_model_calls is True


def test_cassette_miss_live_is_refused_by_name_when_the_repo_has_not_opted_in(
    tmp_path: Path,
) -> None:
    """The named refusal. Before it, `--cassette-miss live` ran and rejected
    every candidate on an environment artifact — a verdict that looked like a
    judgement of the prompt (ADR 0158's live half)."""
    config = _config(_repo(tmp_path, LOGIN_YAML), tmp_path)
    with pytest.raises(LiveGatingDisabledError) as excinfo:
        _live_provider_from_base_ref(config)
    message = str(excinfo.value)
    assert "live gating is off" in message
    assert "gates.live_model_calls: true" in message
    assert "spend your harness quota" in message
    # The CLI already reports this class by name rather than as a rejected
    # candidate, so no command needed a new handler (ADR 0090).
    assert isinstance(excinfo.value, PolicyConfigError)


def test_the_opt_in_is_read_from_the_base_ref_not_the_working_tree(tmp_path: Path) -> None:
    """Trust-critical, and the same rule the policy is read under (ADR 0082):
    a candidate that could turn this on in its own branch would be handing
    itself the operator's login."""
    repo = _repo(tmp_path, LOGIN_YAML)
    (repo / "aef.yaml").write_text(LOGIN_YAML + OPTED_IN)
    config = _config(repo, tmp_path)
    with pytest.raises(LiveGatingDisabledError):
        _live_provider_from_base_ref(config)


def test_the_default_cassette_policy_reads_no_config_and_refuses_nothing(tmp_path: Path) -> None:
    """`cassette_miss="fail"` — every run that is not a prompt candidate —
    returns before touching the config, so the opt-in costs a `git show` on
    exactly the runs that need one."""
    config = _config(_repo(tmp_path, LOGIN_YAML), tmp_path, cassette_miss="fail")
    assert _live_provider_from_base_ref(config) is None
    assert _live_model_calls(config) is False


def test_the_worker_sandbox_is_widened_only_when_a_provider_will_be_built(
    tmp_path: Path,
) -> None:
    """No `--config` means no provider to build worker-side, so widening the
    allowlist would inherit a credential for calls nothing can make."""
    repo = _repo(tmp_path, LOGIN_YAML + OPTED_IN)
    opted_in = _config(repo, tmp_path)
    live = _live_provider_from_base_ref(opted_in)
    assert live is not None
    assert "USER" in _worker_sandbox_policy(opted_in, live).env_allowlist

    unconfigured = LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state2"),
        config_path=None,
        cassette_miss="live",
    )
    assert _live_provider_from_base_ref(unconfigured) is None
    assert "USER" not in _worker_sandbox_policy(unconfigured, None).env_allowlist


# ---------------------------------------------------------------------------
# F-M5-2: the whole provider block crosses the boundary
# ---------------------------------------------------------------------------


def test_the_whole_model_provider_block_crosses_the_wire(tmp_path: Path) -> None:
    """What `_live_provider_from_base_ref` puts on the wire is now the
    validated `ModelProviderConfig` as data — argv template, `isolation:`
    assertion and all — not the two fields F-M5-2 was."""
    config = _config(_repo(tmp_path, COMMAND_YAML + OPTED_IN), tmp_path)
    spec = _live_provider_from_base_ref(config)
    assert spec is not None
    # It survives the framed protocol, which is JSON.
    spec = json.loads(json.dumps(spec))
    assert spec["impl"] == "command"
    assert spec["command"]["argv"] == ["/bin/echo", "{system}", "{prompt}"]
    assert spec["command"]["isolation"] == ["no_tools", "single_turn"]
    assert _live_model_calls(config) is True


def test_a_command_provider_rebuilds_inside_the_worker_and_answers(tmp_path: Path) -> None:
    """The worker end, exactly as `node_worker._configure` does it. With the
    old two-field spec this raised — correctly, there was no `command:`
    block — and the parent reported `worker refused configuration`."""
    from aef.config.factory import build_model_provider
    from aef.providers.command_provider import CommandProvider

    config = _config(_repo(tmp_path, COMMAND_YAML + OPTED_IN), tmp_path)
    spec = _live_provider_from_base_ref(config)
    assert spec is not None
    provider = build_model_provider(
        ModelProviderConfig.model_validate(json.loads(json.dumps(spec)))
    )
    assert isinstance(provider, CommandProvider)
    result = provider.complete(
        CompletionRequest(
            messages=(
                ProviderMessage(role="system", content="be brief"),
                ProviderMessage(role="user", content="ping"),
            ),
            model="",
        )
    )
    assert "ping" in result.content


def test_a_claude_code_config_round_trips_without_making_a_call(tmp_path: Path) -> None:
    """The default provider crosses too, and its argv is rebuilt intact. No
    call is made: only the argv the adapter WOULD run is inspected, which is
    the same surface `isolation` is derived from."""
    from aef.config.factory import build_model_provider
    from aef.providers.harness_provider import PROBE_REQUEST, ClaudeCodeProvider

    config = _config(_repo(tmp_path, LOGIN_YAML + OPTED_IN), tmp_path)
    spec = _live_provider_from_base_ref(config)
    assert spec is not None
    provider = build_model_provider(
        ModelProviderConfig.model_validate(json.loads(json.dumps(spec)))
    )
    assert isinstance(provider, ClaudeCodeProvider)
    # `model:` survived the crossing — it is the provider's default, and a
    # request naming no model of its own gets it.
    assert provider.default_model == "claude-opus-5"
    argv = provider.argv(PROBE_REQUEST)
    assert argv[:2] == ["claude", "-p"]
    # The containment flags are rebuilt intact, which is what makes this the
    # same provider the base ref configured rather than a lookalike.
    assert "--safe-mode" in argv
    assert provider.isolation == ClaudeCodeProvider(default_model="x").isolation


# ---------------------------------------------------------------------------
# The seam itself: a live miss served through the gates' worker
# ---------------------------------------------------------------------------

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


class _Scripted(ModelProvider):
    name = "scripted"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="recorded", model="fake-1", input_tokens=4, output_tokens=2)


def _asking_graph() -> Graph:
    def ask(
        state: AEFState, ctx: object, services: object
    ) -> tuple[StateDelta, str]:  # pragma: no cover - the worker runs the real one
        result = services.require_model_provider().complete(  # type: ignore[attr-defined]
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


def _scenario_with_no_recording() -> Scenario:
    """A scenario whose model call is NOT in the cassette — the shape a
    changed prompt has, and the only shape `--cassette-miss live` exists for."""
    recorded = record_run(
        _asking_graph(),
        AEFState(run_id="s1", agent_id="a", objective="the Kestrel passage"),
        agent_services(model_provider=_Scripted()),
        scenario_id="s1",
        recorded_at=RECORDED_AT,
    )
    payload = {k: v for k, v in recorded.to_payload().items() if k != "model_calls"}
    return Scenario.from_payload({**payload, "id": "miss"})


@pytest.mark.slow
def test_a_live_miss_is_served_inside_the_worker_by_the_rebuilt_provider(
    tmp_path: Path,
) -> None:
    """The whole seam, end to end and offline: a cassette miss under
    `--cassette-miss live` reaches a provider the WORKER built from the base
    ref's config, and answers. Before ADR 0181 this returned
    `IsolationError: worker refused configuration: ... model_provider.impl is
    'command' but no `command:` block is present`, for every scenario in
    every cohort member."""
    ws = Path(tempfile.mkdtemp(dir=tmp_path))
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")
    (ws / "agents" / "graph.py").write_text(ASKER_SOURCE)

    config = _config(_repo(tmp_path, COMMAND_YAML + OPTED_IN), tmp_path)
    live = _live_provider_from_base_ref(config)

    results = run_corpus_isolated(
        ws,
        [_scenario_with_no_recording()],
        entrypoint="agents.graph:build_graph",
        cassette_miss="live",
        live_provider=live,
    )
    assert results["miss"].failure is None, results["miss"].failure
    assert results["miss"].outcome.error_count == 0


@pytest.mark.slow
def test_the_same_miss_fails_when_no_provider_crosses(tmp_path: Path) -> None:
    """The control for the test above: with `live_provider=None` the worker
    has nothing to call, so the miss is a failed node. A live-gating test
    that passed either way would be measuring nothing."""
    ws = Path(tempfile.mkdtemp(dir=tmp_path))
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")
    (ws / "agents" / "graph.py").write_text(ASKER_SOURCE)

    results = run_corpus_isolated(
        ws,
        [_scenario_with_no_recording()],
        entrypoint="agents.graph:build_graph",
        cassette_miss="live",
        live_provider=None,
    )
    assert results["miss"].outcome.error_count == 1


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------


def _branch_with_one_edit(repo: Path) -> None:
    """A candidate branch `cand` holding one Zone C edit — enough for G0 to
    reject on, and cheap enough that nothing is executed."""
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "-b", "cand"], check=True, capture_output=True
    )
    (repo / "aef.yaml").write_text((repo / "aef.yaml").read_text() + "\n# a Zone C edit\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "cand"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "main"], check=True, capture_output=True
    )


def _gate_once(repo: Path, tmp_path: Path, *, cassette_miss: str) -> object:
    """One gate pass that a CHEAP gate rejects, so nothing is executed.

    Deliberately the cheapest possible pass: what is under test is the ledger
    entry, and a gate run that scored a corpus would be paying for evidence
    this assertion does not read.
    """
    from aef.harness.loop import gate

    _branch_with_one_edit(repo)
    config = LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state"),
        config_path="aef.yaml",
        cassette_miss=cassette_miss,
        build_commands=((("/usr/bin/true"),),),
    )
    return gate(config, "cand", now=RECORDED_AT, workdir=tmp_path / "work")


def _gated_detail(tmp_path: Path) -> dict[str, object]:
    from aef.harness import ledger

    entries = ledger.read(LoopPaths(root=tmp_path / "state").ledger_dir)
    gated = [e for e in entries if e.kind is ledger.EventKind.GATED]
    assert len(gated) == 1, entries
    return dict(gated[0].detail)


def test_the_gated_ledger_event_says_whether_candidates_ran_under_the_login(
    tmp_path: Path,
) -> None:
    """A widening of the blast radius that leaves no trace is one nobody can
    audit — the same argument `shadow.containment` records its non-default
    modes on (ADR 0161)."""
    repo = _repo(tmp_path, LOGIN_YAML + OPTED_IN)
    _gate_once(repo, tmp_path, cassette_miss="live")
    assert _gated_detail(tmp_path)["live_model_calls"] is True


def test_the_gated_ledger_event_records_the_ordinary_case_too(tmp_path: Path) -> None:
    """`False` is written, not omitted. An absent key cannot be distinguished
    from a ledger written before the field existed, and the reader would have
    to guess — which is the question the field exists to stop them guessing."""
    repo = _repo(tmp_path, LOGIN_YAML + OPTED_IN)
    _gate_once(repo, tmp_path, cassette_miss="fail")
    detail = _gated_detail(tmp_path)
    assert "live_model_calls" in detail
    assert detail["live_model_calls"] is False


def test_a_live_gate_pass_is_refused_before_a_proposal_is_journalled(tmp_path: Path) -> None:
    """The refusal fires in `_preflight`, so a repo that has not opted in
    never gets a PROPOSED entry it will not get a verdict for."""
    from aef.harness import ledger

    repo = _repo(tmp_path, LOGIN_YAML)
    with pytest.raises(LiveGatingDisabledError):
        _gate_once(repo, tmp_path, cassette_miss="live")
    assert ledger.read(LoopPaths(root=tmp_path / "state").ledger_dir) == ()


def test_the_cli_refuses_a_live_gate_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal at the surface an operator actually types at. Reported as
    a named configuration error on stderr, not as a rejected candidate with a
    G2 reason that names the wrong thing — which is what the whole of ADR
    0158's live half got."""
    from aef.cli.main import main

    repo = _repo(tmp_path, LOGIN_YAML)
    _branch_with_one_edit(repo)

    code = main(
        [
            "loop",
            "gate",
            "--head",
            "cand",
            "--repo",
            str(repo),
            "--state",
            str(tmp_path / "state"),
            "--workdir",
            str(tmp_path / "work"),
            "--config",
            "aef.yaml",
            "--cassette-miss",
            "live",
        ]
    )
    err = capsys.readouterr().err
    assert code != 0
    assert "live gating is off" in err, err
    assert "gates.live_model_calls: true" in err, err


def test_the_worker_never_reads_the_environment_for_a_credential() -> None:
    """`node_worker` builds its live provider from the frame the parent sent
    and from nothing else. Pinned as source, because the alternative — a
    worker reading `os.environ` or the workspace's own `aef.yaml` — is the
    ADR 0082 shape: a candidate judged under rules it supplied."""
    source = (Path(__file__).resolve().parents[2] / "aef/harness/node_worker.py").read_text()
    assert "os.environ" not in source
    assert "load_agent_config" not in source
    assert "ModelProviderConfig.model_validate(live)" in source


def test_the_probe_environment_is_documented_where_the_widening_lives() -> None:
    """The measurement is the justification, so it lives next to the code it
    justifies rather than only in an ADR nobody greps."""
    source = (Path(__file__).resolve().parents[2] / "aef/harness/sandbox.py").read_text()
    assert "Not logged in" in source
    assert "LOGNAME" in source
