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


# --------------------------------------------------------------------------
# Exit 3 is a CRASH, not a HALT (ADR 0167 §6, reported wrong until ADR 0178)
#
# `EXIT_ERROR = 3` was chosen over reusing 2 for one reason: a halt's remedy
# (clear the kill switch) is not a crash's (fix the invocation). Both fail the
# job on `-ge 2`, which is correct — but the failure step was named
# `Surface a halt` and printed `## Self-rewiring loop HALTED` for either, and
# `loop-gate.yml`'s comment listed only 0/1/2. Reproduced by rendering the
# workflow and running its own `case` with status=3.
# --------------------------------------------------------------------------


def _cycle_step() -> dict:
    document = _load("loop-monitor.yml")
    steps = document["jobs"]["monitor"]["steps"]
    return [s for s in steps if s.get("name") == "Daily cycle"][0]


def test_the_nightly_summary_gives_every_exit_code_its_own_words() -> None:
    import re

    run = str(_cycle_step()["run"])
    arms = dict(re.findall(r'\n\s+(\d|\*)\)\s+meaning="([^"]*)"', run))
    assert set(arms) == {"0", "1", "2", "3", "*"}, arms
    assert "HALTED" in arms["2"] and "HALTED" not in arms["3"], arms
    assert "ERROR" in arms["3"] and "crashed" in arms["3"], arms["3"]
    assert arms["2"] != arms["3"], "a halt and a crash must not read the same"


def test_the_failure_step_tells_a_halt_from_a_crash() -> None:
    """It said HALTED for both. The kill switch is the remedy for one of them
    and does not exist for the other."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash exists on every runner here
        pytest.skip("no bash")

    assert 'echo "$status" > "$RUNNER_TEMP/cycle.status"' in str(_cycle_step()["run"]), (
        "the failure step cannot tell a halt from a crash unless the code is recorded"
    )
    steps = _load("loop-monitor.yml")["jobs"]["monitor"]["steps"]
    failing = [s for s in steps if s.get("if") == "failure()"]
    assert len(failing) == 1, [s.get("name") for s in failing]
    body = str(failing[0]["run"])
    body = body[: body.index("aef loop status")]

    printed = {}
    for status in ("2", "3", ""):
        script = body.replace(
            'status=$(cat "$RUNNER_TEMP/cycle.status" 2>/dev/null || echo "")',
            f'status="{status}"',
        )
        done = subprocess.run(
            [bash, "-c", f"GITHUB_STEP_SUMMARY=/dev/stdout\n{script}"],
            capture_output=True,
            text=True,
            check=True,
        )
        printed[status] = done.stdout

    assert "HALTED" in printed["2"] and "HALTED to resume" in printed["2"], printed["2"]
    assert "HALTED" not in printed["3"], printed["3"]
    assert "NOT a halt" in printed["3"] and "invocation" in printed["3"], printed["3"]
    assert "HALTED" not in printed[""] and "FAILED" in printed[""], printed[""]


def test_the_gate_workflow_names_the_exit_code_an_exception_gets() -> None:
    """The comment is the only thing that tells a reader what a non-zero gate
    exit meant, and it stopped at 2 while the CLI grew a 3."""
    from aef.harness.loop import EXIT_ERROR

    text = (WORKFLOWS / "loop-gate.yml").read_text()
    assert f"exit {EXIT_ERROR} =" in text, text
    assert "kill switch" in text
    assert "Not a halt" in text


@pytest.mark.parametrize("name", LOOP_WORKFLOWS)
def test_the_workflows_still_fail_the_job_on_every_code_at_or_above_two(name: str) -> None:
    """The CONTROL for the rewording: the failure RULE is unchanged. An exit
    code chosen without checking the rule that consumes it is how 1 came to
    mean two things (ADR 0167 §6)."""
    from aef.harness.loop import EXIT_ERROR, EXIT_HALTED

    text = (WORKFLOWS / name).read_text()
    if "-ge 2" not in text:
        # `loop-gate.yml` has no status capture at all: any non-zero fails.
        assert "aef loop gate" in text
        return
    assert EXIT_HALTED >= 2 and EXIT_ERROR >= 2


def test_this_repos_nightly_cycle_names_its_graph_id() -> None:
    """This repo's corpus holds two graphs (demo_agent, summary_agent), so a
    cycle without --graph-id refuses — and until ADR 0188 refused with exit
    1, which the workflow's own case statement reads as "the system
    working". The second blind re-score reproduced it. Pin the flag."""
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "loop-monitor.yml"
    ).read_text()
    cycle = text[text.index("aef loop cycle") :]
    cycle = cycle[: cycle.index("tee")]
    assert "--graph-id demo_agent" in cycle, cycle
