"""A17 — a candidate that grants itself the operator's login.

The gates' sandbox worker is the one place this system executes code an agent
wrote, and its environment is scrubbed to `DEFAULT_ENV_ALLOWLIST` so that no
credential is inherited. `gates.live_model_calls: true` widens that allowlist
by exactly one measured variable (`USER`) so `claude -p` can log in — and the
owner's own words for what that buys are: *a candidate's code can then spend
your harness quota*.

So the attack writes it into `aef.yaml` **on its own branch**. Every other
rule the gates judge by is read from the base ref for this reason (ADR 0082):
if an agent can modify what judges it, the judgement carries no information.
`aef.yaml` is Zone C, so G0 would also reject a candidate that changed it —
but this control must hold on its own, because it is the one that binds when
the config was changed on a branch that G0 never saw, or by a hand that is not
the loop's.

Three states are run: the opt-in absent (the default), the opt-in present only
on the candidate's branch (the attack), and the opt-in present on the base ref
(the owner's actual decision).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from aef.harness.git import GitRepo
from aef.harness.loop import (
    LiveGatingDisabledError,
    LiveGatingWithoutConfigError,
    LoopConfig,
    LoopPaths,
    _live_model_calls,
    _live_provider_from_base_ref,
)

BASE_YAML = """extends: _base
model_provider: {impl: claude_code, model: claude-opus-5, fallback: []}
memory: {impl: in_memory}
evaluator: {suites: []}
tools: {allow: []}
policies: {require_hitl_above_risk: 0.0, forbid: []}
objectives: "answer the question"
evolution: {enabled: false}
"""
OPTED_IN = BASE_YAML + "gates: {live_model_calls: true}\n"


def _repo(
    root: Path,
    git: Callable[..., None],
    new_repo: Callable[[Path], None],
    *,
    base_yaml: str,
    branch_yaml: str | None = None,
) -> GitRepo:
    new_repo(root)
    (root / "aef.yaml").write_text(base_yaml, encoding="utf-8")
    (root / "agents").mkdir()
    (root / "agents" / "graph.py").write_text("AGENT = 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    if branch_yaml is not None:
        git(root, "checkout", "-qb", "cand")
        (root / "aef.yaml").write_text(branch_yaml, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "grant myself the login")
    return GitRepo(root=root)


def _config(repo: GitRepo, state: Path, *, cassette_miss: str = "live") -> LoopConfig:
    return LoopConfig(
        repo=repo,
        paths=LoopPaths(root=state),
        base_ref="main",
        config_path="aef.yaml",
        cassette_miss=cassette_miss,
    )


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a17_the_opt_in_on_the_candidates_own_branch_does_not_apply(
    tmp_path: Path,
    git: Callable[..., None],
    new_repo: Callable[[Path], None],
    attack_log: list[str],
) -> None:
    """The whole attack, in one call. The candidate's branch says
    `live_model_calls: true`; the base ref says nothing; the gate refuses."""
    repo = _repo(tmp_path / "repo", git, new_repo, base_yaml=BASE_YAML, branch_yaml=OPTED_IN)
    config = _config(repo, tmp_path / "state")

    assert repo.show("cand", "aef.yaml").endswith("live_model_calls: true}\n"), (
        "the attack fixture does not actually carry the opt-in on the branch"
    )

    with pytest.raises(LiveGatingDisabledError) as excinfo:
        _live_provider_from_base_ref(config)
    attack_log.append(str(excinfo.value))
    assert "live gating is off" in str(excinfo.value)

    # `_live_model_calls` is what the ledger records, and it must not answer
    # "yes" — it goes through the same read, so it refuses too rather than
    # returning True on the candidate's own say-so.
    with pytest.raises(LiveGatingDisabledError):
        _live_model_calls(config)


def test_a17_the_refusal_is_by_name_rather_than_a_rejected_candidate(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """Its own exception type, deliberately: without it the run proceeds, every
    model call misses, ADR 0185 classifies each miss as a dead call, and G2
    reports 'previously-passing scenario(s) no longer pass' — an artifact of
    the environment read as a judgement of the prompt (ADR 0158)."""
    repo = _repo(tmp_path / "repo", git, new_repo, base_yaml=BASE_YAML)
    with pytest.raises(LiveGatingDisabledError):
        _live_provider_from_base_ref(_config(repo, tmp_path / "state"))


def test_a17_live_with_no_config_at_all_is_refused_not_silently_downgraded(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """The hole ADR 0191's F1 closed. "Live with no provider" is not "live
    gating off" — it is a run in which every model call is guaranteed to fail
    and then be excluded."""
    repo = _repo(tmp_path / "repo", git, new_repo, base_yaml=BASE_YAML)
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        base_ref="main",
        config_path=None,
        cassette_miss="live",
    )
    with pytest.raises(LiveGatingWithoutConfigError):
        _live_provider_from_base_ref(config)


def test_a17_the_default_costs_nothing_and_is_not_reached_at_all(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """Under the default `cassette_miss='fail'` no config is read: the refusal
    cannot be a performance or configuration burden on the ordinary path."""
    repo = _repo(tmp_path / "repo", git, new_repo, base_yaml=OPTED_IN)
    config = _config(repo, tmp_path / "state", cassette_miss="fail")
    assert _live_provider_from_base_ref(config) is None
    assert _live_model_calls(config) is False


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a17_the_control_is_load_bearing(
    tmp_path: Path,
    git: Callable[..., None],
    new_repo: Callable[[Path], None],
    monkeypatch: pytest.MonkeyPatch,
    attack_log: list[str],
) -> None:
    """Read the config from the candidate's ref instead of the base ref —
    one word — and the candidate's own `aef.yaml` grants it the login.

    Two halves are asserted, because either alone is ambiguous:

    1. With the base-ref read replaced by a head-ref read, the SAME repo and
       the SAME call returns a provider instead of raising. The candidate
       wrote the rule it was judged by.
    2. The owner's real decision still works: with the opt-in on the base ref,
       the unmutated code returns the provider. A control that refused
       everything would pass every test above while breaking the feature.
    """
    repo = _repo(tmp_path / "repo", git, new_repo, base_yaml=BASE_YAML, branch_yaml=OPTED_IN)
    config = _config(repo, tmp_path / "state")

    import aef.harness.loop as loop_module
    from aef.config.loader import load_agent_config_text

    def from_the_candidates_ref(cfg: LoopConfig):  # type: ignore[no-untyped-def]
        return load_agent_config_text(cfg.repo.show("cand", "aef.yaml"), source="cand:aef.yaml")

    monkeypatch.setattr(loop_module, "_agent_config_from_base_ref", from_the_candidates_ref)

    granted = _live_provider_from_base_ref(config)
    attack_log.append(f"provider granted from the candidate's own branch: {granted}")
    assert granted is not None, attack_log
    assert granted["impl"] == "claude_code", attack_log
    assert _live_model_calls(config) is True, attack_log

    # Half two, with the control back in place and the opt-in where it belongs.
    monkeypatch.undo()
    owner = _repo(tmp_path / "owner-repo", git, new_repo, base_yaml=OPTED_IN)
    owner_config = _config(owner, tmp_path / "owner-state")
    assert _live_provider_from_base_ref(owner_config) is not None
    assert _live_model_calls(owner_config) is True
