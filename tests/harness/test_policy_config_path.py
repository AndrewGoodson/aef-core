"""`policies` and `tools.allow` now reach a run.

They validated and were ignored, so an adopter setting
`require_hitl_above_risk` believed it enforced and got the engine's own
default instead (ADR 0014, ADR 0079). The gate additionally ran every
candidate under a total-denial policy no production run would ever match, so
`Outcome.policy_denials` saturated on both sides and could never differ
(ADR 0080).

The trust-critical part: the gate reads the config **from the base ref**.
`aef.yaml` is Zone C, but the gate must read it the way it reads every other
rule it judges by, or a candidate that edited it would be judged under rules
it wrote (ADR 0082).
"""

import subprocess
from pathlib import Path

import pytest

from aef.config import PoliciesConfig, ToolsConfig, build_policy_config
from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, _policy_from_base_ref
from aef.security.tool import PolicyConfig

BASE_YAML = """extends: _base
model_provider: {impl: anthropic, model: claude-sonnet, fallback: []}
memory: {impl: in_memory}
evaluator: {suites: []}
tools: {allow: [safe.read]}
policies: {require_hitl_above_risk: 0.1, forbid: [rm_rf]}
objectives: "do the thing"
evolution: {enabled: false}
"""


def _repo(tmp_path: Path, yaml_text: str = BASE_YAML) -> Path:
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


def _config(repo: Path, tmp_path: Path, *, config_path: str | None = "aef.yaml") -> LoopConfig:
    return LoopConfig(
        repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"), config_path=config_path
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


# --------------------------------------------------------------------------
# The mapping
# --------------------------------------------------------------------------


def test_tools_allow_are_scopes_and_policies_forbid_are_names() -> None:
    """The engine gates on `tool.required_scopes`, so an allowlist of NAMES
    could not authorise anything — every tool would still be denied for
    missing scopes and the field would do nothing."""
    built = build_policy_config(
        ToolsConfig(allow=["net.read", "fs.read"]),
        PoliciesConfig(require_hitl_above_risk=0.4, forbid=["rm_rf"]),
    )
    assert built.allowed_scopes == frozenset({"net.read", "fs.read"})
    assert built.forbidden_tool_names == frozenset({"rm_rf"})
    assert built.require_hitl_above_risk == 0.4


def test_an_empty_config_allows_nothing() -> None:
    """Deny-by-default must survive being configurable."""
    assert build_policy_config(ToolsConfig(), PoliciesConfig()) == PolicyConfig()


def test_the_configured_policy_actually_binds() -> None:
    """Behaviour, not construction: a scope the config omits is denied and a
    scope it names is not."""
    from dataclasses import dataclass
    from typing import Any

    from aef.security.tool import PolicyEngine, Tool, ToolCall

    @dataclass(frozen=True)
    class _Tool(Tool):
        name: str
        required_scopes: tuple[str, ...] = ()

        def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
            return {}

    engine = PolicyEngine(build_policy_config(ToolsConfig(allow=["net.read"]), PoliciesConfig()))
    allowed = _Tool(name="fetch", required_scopes=("net.read",))
    denied = _Tool(name="write", required_scopes=("fs.write",))

    def _decide(tool: _Tool) -> str:
        call = ToolCall(tool_name=tool.name, arguments={}, risk=0.0)
        return engine.evaluate(tool, call).decision.value

    assert _decide(allowed) == "allow"
    assert _decide(denied) == "deny", "a scope the config omits must still be denied"


# --------------------------------------------------------------------------
# The trust boundary
# --------------------------------------------------------------------------


def test_the_gate_reads_the_policy_from_the_base_ref(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    config = _config(repo, tmp_path)
    base = _policy_from_base_ref(config)
    assert base is not None
    assert base.allowed_scopes == frozenset({"safe.read"})


def test_a_candidate_cannot_widen_the_policy_it_is_judged_by(tmp_path: Path) -> None:
    """The planted fault: the candidate branch grants itself a new scope,
    clears the deny list, and raises the HITL threshold to 0.99."""
    repo = _repo(tmp_path)
    config = _config(repo, tmp_path)
    before = _policy_from_base_ref(config)

    _git(repo, "checkout", "-q", "-b", "cand")
    (repo / "aef.yaml").write_text(
        BASE_YAML.replace("allow: [safe.read]", "allow: [safe.read, danger.write]")
        .replace("require_hitl_above_risk: 0.1", "require_hitl_above_risk: 0.99")
        .replace("forbid: [rm_rf]", "forbid: []")
    )
    _git(repo, "commit", "-qam", "widen my own policy")
    _git(repo, "checkout", "-q", "main")

    assert _policy_from_base_ref(config) == before, (
        "the candidate changed the rules it is judged by"
    )


def test_the_reader_is_not_simply_inert(tmp_path: Path) -> None:
    """The control for the test above. A function that always returned the
    same thing would pass it and be useless — an owner's change on the base
    ref must be seen."""
    repo = _repo(tmp_path)
    config = _config(repo, tmp_path)

    (repo / "aef.yaml").write_text(
        BASE_YAML.replace("allow: [safe.read]", "allow: [safe.read, owner.added]")
    )
    _git(repo, "commit", "-qam", "owner widens on main")

    policy = _policy_from_base_ref(config)
    assert policy is not None and "owner.added" in policy.allowed_scopes


def test_no_config_path_means_deny_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _policy_from_base_ref(_config(repo, tmp_path, config_path=None)) is None


def test_an_unreadable_policy_denies_rather_than_passing(tmp_path: Path) -> None:
    """A config that does not parse must not silently become "no restrictions"."""
    repo = _repo(tmp_path, yaml_text="this: [is, not, a, valid, agent, config\n")
    assert _policy_from_base_ref(_config(repo, tmp_path)) == PolicyConfig()


def test_a_missing_config_at_the_base_ref_is_not_an_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _policy_from_base_ref(_config(repo, tmp_path, config_path="nope.yaml")) is None


# --------------------------------------------------------------------------
# It reaches the sandbox as data
# --------------------------------------------------------------------------


def test_the_runner_takes_the_policy_as_data_not_from_the_workspace() -> None:
    """Reading `aef.yaml` from the workspace inside the sandbox would read the
    candidate's copy — the whole point of passing it in."""
    import inspect

    from aef.harness.scenario_runner import policy_config_from_payload, run_scenario

    assert "policy" in inspect.signature(run_scenario).parameters
    assert policy_config_from_payload(None) == PolicyConfig()
    assert policy_config_from_payload(
        {"allowed_scopes": ["a"], "forbidden_tool_names": ["b"], "require_hitl_above_risk": 0.5}
    ) == PolicyConfig(
        allowed_scopes=frozenset({"a"}),
        forbidden_tool_names=frozenset({"b"}),
        require_hitl_above_risk=0.5,
    )


@pytest.mark.parametrize("flag_owner", ["gate", "cycle"])
def test_the_cli_exposes_config(flag_owner: str) -> None:
    from aef.cli.loop import _config as build_loop_config
    from aef.cli.main import build_parser

    args = build_parser().parse_args(
        [
            "loop",
            flag_owner,
            "--state",
            "/tmp/aef-state-not-in-repo",
            "--workdir",
            "/tmp/w",
            *(["--head", "x"] if flag_owner == "gate" else []),
            "--config",
            "aef.yaml",
        ]
    )
    assert build_loop_config(args).config_path == "aef.yaml"
