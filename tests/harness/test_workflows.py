"""The CI workflows are Zone B, and their triggers are a security decision.

This file exists because "we remembered not to add `pull_request_target`" is
not a control. The trap is subtle enough that it will look like a
convenience improvement to someone in six months, so it is asserted rather
than reviewed for.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(".github/workflows")
LOOP_WORKFLOWS = ("loop-gate.yml", "loop-monitor.yml")

# `on:` parses to the boolean True in YAML 1.1 unless quoted — a well-known
# footgun that would make a naive trigger check silently pass by looking at
# the wrong key.
ON_KEY = True


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _triggers(name: str) -> dict:
    document = _load(name)
    on = document.get(ON_KEY, document.get("on"))
    assert on is not None, f"{name} declares no triggers at all"
    return on if isinstance(on, dict) else dict.fromkeys(on)


@pytest.mark.parametrize("name", LOOP_WORKFLOWS)
def test_the_loop_workflow_exists(name: str) -> None:
    assert (WORKFLOWS / name).is_file()


@pytest.mark.parametrize("name", LOOP_WORKFLOWS)
@pytest.mark.parametrize("forbidden", ["pull_request", "pull_request_target"])
def test_no_pull_request_trigger(name: str, forbidden: str) -> None:
    """THE trap.

    `pull_request` runs the workflow from the PR's merge commit, so a
    candidate editing `.github/workflows/` supplies the workflow that judges
    it. `pull_request_target` runs the base's workflow but carries full
    secrets into a job that may check out candidate code.
    """
    assert forbidden not in _triggers(name), (
        f"{name} must not trigger on {forbidden}: it would let a candidate influence, or "
        f"extract secrets from, the job that judges it"
    )


@pytest.mark.parametrize("name", LOOP_WORKFLOWS)
def test_only_dispatch_and_schedule_trigger_the_loop(name: str) -> None:
    # Allowlist, not denylist — a trigger added later is denied by having
    # been left out rather than by having been foreseen.
    assert set(_triggers(name)) <= {"workflow_dispatch", "schedule"}


@pytest.mark.parametrize("name", LOOP_WORKFLOWS)
def test_the_loop_job_is_read_only(name: str) -> None:
    # A judge that can also push is not a judge.
    assert _load(name)["permissions"] == {"contents": "read"}


def test_the_gate_checks_out_main_never_the_candidate() -> None:
    document = _load("loop-gate.yml")
    steps = document["jobs"]["gate"]["steps"]
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]

    assert checkouts, "loop-gate.yml must check something out explicitly"
    for step in checkouts:
        assert step.get("with", {}).get("ref") == "main", (
            "the gate job must check out main. Checking out the candidate would run the "
            "candidate's harness — the exact failure ADR 0047 exists to prevent."
        )


def test_the_gate_runs_in_a_network_isolated_container() -> None:
    # The attestation passed to `--network-isolated` is only true if
    # something actually provides isolation.
    container = _load("loop-gate.yml")["jobs"]["gate"]["container"]
    assert "--network none" in container["options"]


def test_the_attestation_flag_is_only_passed_where_isolation_exists() -> None:
    gate = (WORKFLOWS / "loop-gate.yml").read_text()
    monitor = (WORKFLOWS / "loop-monitor.yml").read_text()
    assert "--network-isolated" in gate
    # loop-monitor runs no candidate code, so it neither needs nor claims it.
    assert "--network-isolated" not in monitor


def test_no_secrets_are_referenced_by_the_loop_workflows() -> None:
    """The sandbox scrubs the environment it hands to a child, but a secret
    injected as a workflow-level env var would be in the parent to begin
    with. Not referencing any is the stronger property."""
    for name in LOOP_WORKFLOWS:
        text = (WORKFLOWS / name).read_text()
        assert "secrets." not in text, f"{name} references a secret"


def test_the_ordinary_ci_workflow_is_untouched_by_the_loop() -> None:
    # ci.yml is the repo's own green bar and has nothing to do with the loop.
    triggers = _triggers("ci.yml")
    assert "pull_request" in triggers  # normal, correct, and not a loop workflow
    assert "loop" not in (WORKFLOWS / "ci.yml").read_text()


@pytest.mark.parametrize("name", LOOP_WORKFLOWS)
def test_loop_state_lives_outside_the_checkout(name: str) -> None:
    """State inside the working tree is swept into candidate diffs by
    `git add -A`, making the audit trail part of what it audits. The driver
    refuses it; this pins that the workflows do not try."""
    text = (WORKFLOWS / name).read_text()
    assert "--state ~/" in text or "--state /" in text, (
        f"{name} must pass a --state path outside the repository checkout"
    )
    assert "--state ." not in text
