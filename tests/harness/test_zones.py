"""Zone classification — the write-scope boundary that makes self-coding
survivable (ADR 0044).

Deny-by-default is the whole point: anything the classifier cannot prove is
Zone A must come back non-writable. Every ambiguous, malformed, or hostile
path in here is required to land on the deny side, not merely "somewhere".
"""

import pytest

from aef.harness.zones import (
    Zone,
    ZonePolicy,
    classify_path,
    enforce_zones,
)

# --------------------------------------------------------------------------
# Straightforward classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "agents/foo.py",
        "agents/deep/nested/module.py",
        "agents/__init__.py",
        "agents/config.yaml",
    ],
)
def test_agent_paths_are_zone_a(path: str) -> None:
    assert classify_path(path) is Zone.A


@pytest.mark.parametrize(
    "path",
    [
        "aef/harness/zones.py",
        "tests/harness/test_zones.py",
        ".github/workflows/ci.yml",
        "corpus/scenario_001.json",
        "evals/suite.yaml",
    ],
)
def test_harness_paths_are_zone_b(path: str) -> None:
    # Zone B is what judges the candidate. If an agent can edit it, the
    # judgement carries no information.
    assert classify_path(path) is Zone.B


@pytest.mark.parametrize(
    "path",
    [
        "aef/kernel/executor.py",
        "aef/evolution/engine.py",
        "tests/kernel/test_executor.py",
        "docs/adr/0044-self-coding.md",
        "pyproject.toml",
        "README.md",
    ],
)
def test_core_paths_are_zone_c(path: str) -> None:
    assert classify_path(path) is Zone.C


def test_a_lookalike_harness_dir_under_the_agent_root_is_still_zone_a() -> None:
    # Zone B is a fixed set of real paths, not the word "harness". A
    # directory an agent names `harness` inside its own zone judges nothing.
    assert classify_path("agents/harness/gate.py") is Zone.A
    # ...and naming a workflow after the agent zone does not make it Zone A.
    assert classify_path(".github/workflows/agents.yml") is Zone.B


# --------------------------------------------------------------------------
# Adversarial paths — every one of these must land on the deny side
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "agents/../aef/kernel/executor.py",
        "agents/../../etc/passwd",
        "agents/sub/../../aef/security/tool.py",
        "../agents/foo.py",
        "..",
    ],
)
def test_path_traversal_never_reaches_zone_a(path: str) -> None:
    assert classify_path(path) is not Zone.A


@pytest.mark.parametrize("path", ["/agents/foo.py", "/etc/passwd", "/aef/kernel/executor.py"])
def test_absolute_paths_never_reach_zone_a(path: str) -> None:
    # Diffs are repo-relative by construction; an absolute path means
    # something built the path list wrong, or is probing.
    assert classify_path(path) is not Zone.A


@pytest.mark.parametrize("path", ["agentsfoo/x.py", "agents_extra/x.py", "myagents/x.py"])
def test_a_prefix_that_merely_starts_with_the_root_is_not_zone_a(path: str) -> None:
    # "agents" must match a path *segment*, not a string prefix.
    assert classify_path(path) is not Zone.A


@pytest.mark.parametrize("path", ["AGENTS/x.py", "Agents/x.py", "aGeNtS/x.py"])
def test_case_variants_are_not_zone_a(path: str) -> None:
    # macOS filesystems are case-insensitive by default, so AGENTS/x.py and
    # agents/x.py can be the same file on disk while git treats them as
    # different paths. Deny the variant rather than guess.
    assert classify_path(path) is not Zone.A


@pytest.mark.parametrize("path", ["", "   ", ".", "./"])
def test_degenerate_paths_are_not_zone_a(path: str) -> None:
    assert classify_path(path) is not Zone.A


def test_a_leading_dot_slash_still_classifies_normally() -> None:
    assert classify_path("./agents/foo.py") is Zone.A


@pytest.mark.parametrize("path", ["agents\\foo.py", "agents\\..\\aef\\kernel\\executor.py"])
def test_backslash_separators_never_reach_zone_a(path: str) -> None:
    # git emits forward slashes. A backslash is either a literal filename
    # character or a Windows-style path someone constructed by hand; either
    # way it is not a path this classifier will vouch for.
    assert classify_path(path) is not Zone.A


def test_a_null_byte_never_reaches_zone_a() -> None:
    assert classify_path("agents/foo.py\x00.txt") is not Zone.A


def test_a_bare_agent_root_is_not_zone_a() -> None:
    # The directory itself is not a file a diff can contain.
    assert classify_path("agents") is not Zone.A


# --------------------------------------------------------------------------
# Enforcement
# --------------------------------------------------------------------------


def test_an_all_zone_a_diff_is_allowed() -> None:
    verdict = enforce_zones(["agents/a.py", "agents/b.py"])
    assert verdict.allowed
    assert verdict.rejected == ()
    assert verdict.security_events == ()


def test_a_zone_c_path_rejects_the_whole_candidate() -> None:
    verdict = enforce_zones(["agents/a.py", "aef/kernel/executor.py"])
    assert not verdict.allowed
    assert [v.path for v in verdict.rejected] == ["aef/kernel/executor.py"]


def test_a_zone_b_path_is_flagged_as_a_security_event_not_a_normal_rejection() -> None:
    # ADR 0045: a diff reaching the harness is a security event, not a
    # proposal. The distinction drives halt criteria, so it must be visible.
    verdict = enforce_zones(["agents/a.py", "aef/harness/zones.py"])
    assert not verdict.allowed
    assert [v.path for v in verdict.security_events] == ["aef/harness/zones.py"]


def test_a_zone_c_rejection_is_not_a_security_event() -> None:
    verdict = enforce_zones(["aef/kernel/executor.py"])
    assert verdict.rejected
    assert verdict.security_events == ()


def test_a_traversal_attempt_is_a_security_event() -> None:
    verdict = enforce_zones(["agents/../aef/kernel/executor.py"])
    assert not verdict.allowed
    assert len(verdict.security_events) == 1
    assert "traversal" in verdict.security_events[0].reason.lower()


def test_an_empty_diff_is_allowed_but_records_nothing() -> None:
    # A no-op candidate is not a zone violation; it is rejected later, by
    # the proposer's no-op rule, not here.
    verdict = enforce_zones([])
    assert verdict.allowed
    assert verdict.verdicts == ()


def test_every_rejection_carries_a_reason() -> None:
    verdict = enforce_zones(
        ["aef/kernel/executor.py", "aef/harness/zones.py", "agents/../x.py", "AGENTS/x.py"]
    )
    assert len(verdict.rejected) == 4
    assert all(v.reason for v in verdict.rejected)


def test_the_agent_root_is_configurable_for_an_adopting_repo() -> None:
    policy = ZonePolicy(agent_root="src/my_agents")
    assert classify_path("src/my_agents/foo.py", policy) is Zone.A
    assert classify_path("agents/foo.py", policy) is Zone.C


def test_a_configured_agent_root_cannot_swallow_zone_b() -> None:
    # The load-bearing property: even if the agent root is configured to the
    # repo root, harness paths stay Zone B. Otherwise config becomes the
    # escape hatch. (Config lives in Zone C and gates read it from the base
    # ref, so this is defence in depth — but it must hold on its own.)
    policy = ZonePolicy(agent_root="")
    assert classify_path("aef/harness/zones.py", policy) is Zone.B
    assert classify_path(".github/workflows/ci.yml", policy) is Zone.B


def test_zone_b_patterns_are_not_configurable() -> None:
    # There is no constructor argument that shrinks Zone B. If one is ever
    # added, this test should fail and the reviewer should ask why.
    assert "harness" not in ZonePolicy.__dataclass_fields__
    assert set(ZonePolicy.__dataclass_fields__) == {"agent_root"}
