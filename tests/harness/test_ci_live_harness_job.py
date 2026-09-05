"""The CI job that exercises the harness backends wherever it can (ADR 0199).

J0b scored dimension 8 down because *"the Codex path is never exercised
against the real CLI — its only live test is one of the three skips"*. The
live tests are opt-in twice over for good reasons (they spend the operator's
quota and take seconds), and the consequence is that on every hosted runner
they are skips, so `pytest -q` being green says nothing at all about the two
backends the "works with any coding agent" claim rests on.

The job added to `ci.yml` runs them where a CLI and a credential exist and
prints why it did not otherwise. **What is tested here is the shell it runs**,
extracted from the workflow itself so the two cannot drift — a YAML-shape
assertion would pass against a detector that never emits a target, which is
the same class of test ADR 0150 caught asserting the shape of a flag whose
value the CLI rejected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

CI = Path(".github/workflows/ci.yml")
JOB = "live-harness"


def _job() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"][JOB]


def _step(name: str) -> dict:
    for step in _job()["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"{JOB} has no step named {name!r}")


def _detect_script() -> str:
    return str(_step("Which harness backends can answer here")["run"])


def _run_detect(tmp_path: Path, env: dict[str, str]) -> str:
    script = tmp_path / "detect.sh"
    # `$GITHUB_OUTPUT`/`$GITHUB_STEP_SUMMARY` exist in Actions and not here, so
    # they are pointed at files rather than stripped: the redirection is part
    # of the block under test and a detector that crashed writing its own
    # output would still "pass" if the lines were removed.
    script.write_text(_detect_script())
    completed = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={
            "GITHUB_OUTPUT": str(tmp_path / "out"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            **env,
        },
    )
    assert completed.returncode == 0, completed.stderr
    return (tmp_path / "out").read_text()


def test_the_job_exists_and_is_pointable_at_a_runner_that_has_the_clis() -> None:
    """A hosted runner has neither CLI, so the job would be a permanent skip
    unless an owner can aim it somewhere. `vars.AEF_LIVE_RUNNER` is that aim,
    with the hosted runner as the default — the job is never unschedulable."""
    runs_on = str(_job()["runs-on"])
    assert "AEF_LIVE_RUNNER" in runs_on
    assert "ubuntu-latest" in runs_on


def test_a_runner_with_no_cli_selects_nothing_and_the_build_does_not_fail(
    tmp_path: Path,
) -> None:
    """The skip, RUN rather than read: no CLI on PATH and no home directory
    means an empty target list, and the step that would spend quota is guarded
    on exactly that string."""
    output = _run_detect(
        tmp_path, {"HOME": str(tmp_path / "nohome"), "PATH": "/usr/bin:/bin"}
    )
    assert output.strip().endswith("targets=") or output.strip() == "targets="
    assert _step("Live harness tests")["if"] == "steps.detect.outputs.targets != ''"
    # ...and the complementary branch prints the reason. A skip that prints
    # nothing is indistinguishable from a pass, which is the failure ADR 0188
    # found in this repo's own nightly job.
    explain = _step("No backend to exercise")
    assert explain["if"] == "steps.detect.outputs.targets == ''"
    assert "AEF_LIVE_RUNNER" in str(explain["run"])


def _bin_with_a_fake_codex(tmp_path: Path) -> str:
    """A PATH on which `codex` exists.

    A stub rather than `shutil.which("codex")`, which was the first spelling
    and made both tests below `pytest.skip` on any machine without the CLI —
    including every CI runner, which is the exact "the only live test is one of
    the three skips" hole this job exists to close. The detector asks `command
    -v codex`, so a file with the name and the execute bit is the whole of what
    it is entitled to see; nothing here runs it.
    """
    binary = tmp_path / "bin" / "codex"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\necho codex-cli 0.0.0-stub\n")
    binary.chmod(0o755)
    return f"{binary.parent}:/usr/bin:/bin"


def test_a_cli_without_a_credential_is_not_selected(tmp_path: Path) -> None:
    """Present-but-not-logged-in is the state a hosted runner with an install
    step would be in, and running the tests there would fail the build for a
    fact about the runner rather than about the code."""
    output = _run_detect(
        tmp_path,
        {"HOME": str(tmp_path / "nohome"), "PATH": _bin_with_a_fake_codex(tmp_path)},
    )
    assert "targets=" in output
    assert "test_codex_live.py" not in output


def test_a_credential_from_secrets_selects_the_backend(tmp_path: Path) -> None:
    """The other form a credential takes. An owner with no self-hosted machine
    supplies a key as a repository secret, and the same job then exercises the
    adapter on a hosted runner that has installed the CLI."""
    output = _run_detect(
        tmp_path,
        {
            "HOME": str(tmp_path / "nohome"),
            "PATH": _bin_with_a_fake_codex(tmp_path),
            "OPENAI_API_KEY": "sk-not-a-real-key",
        },
    )
    assert "tests/providers/test_codex_live.py" in output


def test_the_cli_s_own_login_file_selects_the_backend(tmp_path: Path) -> None:
    """The form this repo's own machine is in: no API key anywhere, and the
    credential is the file `codex login` wrote. ADR 0112's whole claim is that
    an adopter needs no API key, so a detector that only understood secrets
    would never run the path on the box the path was built for."""
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("{}")
    output = _run_detect(
        tmp_path, {"HOME": str(home), "PATH": _bin_with_a_fake_codex(tmp_path)}
    )
    assert "tests/providers/test_codex_live.py" in output


def test_the_live_step_sets_the_opt_in_the_tests_require() -> None:
    """`needs_codex`/`needs_claude` skip unless `AEF_LIVE_HARNESS` is set, so a
    job that ran pytest without it would report two passes that were two
    skips — green, and measuring nothing."""
    assert _step("Live harness tests")["env"]["AEF_LIVE_HARNESS"] == "1"
    assert "pytest" in str(_step("Live harness tests")["run"])
