"""Execute the rendered workflow's preparation and Docker boundary as shell.

Git and tar run for real against a disposable repository. The Docker recorder
asserts argv/failure handling, not actual network isolation; the latter also
has a separate bounded Docker smoke recorded in the release review evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from aef.cli.adopt_loop import render_loop_gate_workflow


def _job(core: bool = False) -> dict[str, Any]:
    return yaml.safe_load(render_loop_gate_workflow("aef-core", core=core))["jobs"]["gate"]


def _step(name: str, *, core: bool = False) -> str:
    return str(next(s for s in _job(core)["steps"] if s.get("name") == name)["run"])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    origin = tmp_path / "origin with spaces"
    origin.mkdir()
    _git(origin, "init", "--initial-branch=main")
    _git(origin, "config", "user.name", "Fixture")
    _git(origin, "config", "user.email", "fixture@example.invalid")
    (origin / "trusted.txt").write_text("base\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "base")
    # This is a valid Git ref, including executable-looking punctuation.
    # Git/shell must treat the input as DATA, even when it passes validation.
    branch = "candidate$(touch${IFS}HOST_EXECUTED)"
    _git(origin, "checkout", "-b", branch)
    (origin / "setup.py").write_text("raise RuntimeError('candidate executed on host')\n")
    (origin / "candidate.txt").write_text("candidate\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "candidate")
    checkout = tmp_path / "checkout with spaces"
    subprocess.run(
        ["git", "clone", "--branch", "main", str(origin), str(checkout)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(checkout, "config", "http.https://example.invalid/.extraheader", "FAKE_CREDENTIAL")
    hook = checkout / ".git/hooks/post-checkout"
    hook.write_text("#!/bin/sh\ntouch HOST_HOOK_EXECUTED\n")
    hook.chmod(0o755)
    shim = tmp_path / "bin"
    shim.mkdir()
    docker = shim / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['DOCKER_RECORD']).write_text(json.dumps(sys.argv[1:]))\n"
        "sys.exit(int(os.environ.get('DOCKER_EXIT', '0')))\n"
    )
    docker.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "PATH": str(shim) + os.pathsep + env["PATH"],
            "HOME": str(home),
            "AEF_GATE_ROOT": str(tmp_path / "gate with spaces"),
            "AEF_GATE_IMAGE": "aef-workflow-fixture:local",
            "GITHUB_WORKSPACE": str(checkout),
            "AEF_CANDIDATE_REF": branch,
            "AEF_ENTRYPOINT": "agents.fixture:build_graph",
            "AEF_BUILD_COMMAND": "python -m pytest -q",
            "DOCKER_RECORD": str(tmp_path / "docker.json"),
        }
    )
    return checkout, env


def _run(
    step: str, fixture: tuple[Path, dict[str, str]], *, core: bool = False
) -> subprocess.CompletedProcess[str]:
    checkout, env = fixture
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _step(step, core=core)],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_core_workflow_is_the_same_audited_template() -> None:
    assert Path(".github/workflows/loop-gate.yml").read_text() == render_loop_gate_workflow(
        "aef-core", core=True
    )
    for core in (True, False):
        job = _job(core)
        assert (
            job["if"]
            == "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'"
        )
        assert "container" not in job
        steps = [s.get("name") for s in job["steps"]]
        assert (
            steps.index("Build the trusted runtime image")
            < steps.index("Fetch the candidate as data")
            < steps.index("Gate")
        )
        fetch = next(s for s in job["steps"] if s.get("name") == "Fetch the candidate as data")
        assert fetch["env"]["AEF_CANDIDATE_REF"] == "${{ inputs.head }}"
        assert "${{" not in fetch["run"]


@pytest.mark.parametrize("core", [False, True])
def test_only_committed_base_enters_image_then_candidate_enters_clean_repo(
    prepared: tuple[Path, dict[str, str]], core: bool
) -> None:
    checkout, env = prepared
    (checkout / "untracked-secret.txt").write_text("not part of the image\n")
    built = _run("Build the trusted runtime image", prepared, core=core)
    assert built.returncode == 0, built.stderr
    image = Path(env["AEF_GATE_ROOT"]) / "image"
    assert {p.name for p in image.iterdir()} == {"source", "Dockerfile"}
    assert {p.name for p in (image / "source").iterdir()} == {"trusted.txt"}
    dockerfile = (image / "Dockerfile").read_text()
    assert "install -y --no-install-recommends git" in dockerfile
    assert "|| true" not in dockerfile
    assert ('pip install "/opt/aef-base[dev]"' in dockerfile) is core
    fetched = _run("Fetch the candidate as data", prepared, core=core)
    assert fetched.returncode == 0, fetched.stderr
    clean = Path(env["AEF_GATE_ROOT"]) / "repo"
    assert _git(clean, "rev-parse", "HEAD") == _git(checkout, "rev-parse", "main")
    assert _git(clean, "show", "refs/loop/candidate:candidate.txt") == "candidate"
    assert not (clean / "candidate.txt").exists()
    assert not (clean / "setup.py").exists()
    assert "FAKE_CREDENTIAL" not in (clean / ".git/config").read_text()
    assert not (clean / ".git/hooks/post-checkout").exists()
    for directory in (checkout, clean):
        assert not (directory / "HOST_EXECUTED").exists()
        assert not (directory / "HOST_HOOK_EXECUTED").exists()


@pytest.mark.parametrize(
    "branch", ["", "../main", "main:refs/heads/main", "main\nmain", "main $(touch HOST_EXECUTED)"]
)
def test_invalid_branch_ref_fails_before_fetch(
    prepared: tuple[Path, dict[str, str]], branch: str
) -> None:
    checkout, env = prepared
    env["AEF_CANDIDATE_REF"] = branch
    done = _run("Fetch the candidate as data", prepared)
    assert done.returncode != 0
    assert not (Path(env["AEF_GATE_ROOT"]) / "repo").exists()
    assert not (checkout / "HOST_EXECUTED").exists()
    refs = _git(checkout, "for-each-ref", "refs/loop")
    assert not refs


@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 125])
def test_gate_isolated_argv_and_failure_have_no_host_fallback(
    prepared: tuple[Path, dict[str, str]], exit_code: int
) -> None:
    _, env = prepared
    env["DOCKER_EXIT"] = str(exit_code)
    # The CLI shim does not execute a container; assert exact shell/argv only.
    result = _run("Gate", prepared)
    assert result.returncode == exit_code
    args = json.loads(Path(env["DOCKER_RECORD"]).read_text())
    assert args[:7] == ["run", "--rm", "--pull", "never", "--network", "none", "--read-only"]
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert args[args.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
    assert mounts == [
        f"type=bind,src={env['AEF_GATE_ROOT']}/repo,dst=/repo,readonly",
        f"type=bind,src={env['HOME']}/.aef-loop-state,dst=/state",
    ]
    assert [args[i + 1] for i, arg in enumerate(args) if arg == "--env"] == ["HOME=/tmp"]
    assert "/tmp:rw,exec,mode=1777" in args and "/work:rw,exec,mode=1777" in args
    assert args[args.index("--entrypoint") + 1] == env["AEF_ENTRYPOINT"]
    assert args[args.index("--build-command") + 1] == env["AEF_BUILD_COMMAND"]
    assert args[-1] == "--network-isolated"
    assert Path(env["HOME"], ".aef-loop-state").is_dir()
