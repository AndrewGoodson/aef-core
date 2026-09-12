"""Run bounded integration mutations in disposable source copies only.

Usage: python -B SCRIPT /absolute/aef-source /absolute/existing/output-dir
Logs and mutation_checks.json are saved in the explicit output directory. Nothing in the
source checkout is written; the copied package is the only import source.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path(sys.argv[1]).resolve(strict=True)
OUTPUT = Path(sys.argv[2]).resolve(strict=True)
if OUTPUT == SOURCE or OUTPUT.is_relative_to(SOURCE):
    raise ValueError("mutation evidence must be written outside the source checkout")
MODULE = Path("aef/cli/migrate.py")
TEST = Path("tests/cli/test_migrate_prompt_agents.py")
BOOTSTRAP = """
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import aef.cli.migrate
assert Path(aef.cli.migrate.__file__).resolve() == root / "aef/cli/migrate.py"
print("Imported disposable module:", aef.cli.migrate.__file__, flush=True)
import pytest
raise SystemExit(pytest.main(sys.argv[2:]))
"""

CASES = (
    {
        "name": "native_nonregular_source_rejection",
        "selector": "test_discovery_refuses_nonregular_personas_before_reading",
        "original": (
            "            if not path.is_file():\n"
            '                raise PromptAgentError(f"refusing nonregular agent file: {rel}")\n'
        ),
        "replacement": "            # MUTATION: allow nonregular persona sources through.\n",
        "expected_tests": 3,
    },
    {
        "name": "existing_prompt_graph_identity_recovery",
        "selector": "test_adding_a_colliding_persona_preserves_prior_graph_identity",
        "original": "    previous, used, graph_ids = _existing_prompt_graphs(root, agent_root)\n",
        "replacement": "    previous, used, graph_ids = {}, set(), set()  # MUTATION\n",
        "expected_tests": 2,
    },
)


def run_case(root: Path, name: str, selector: str, phase: str) -> dict[str, object]:
    command = [
        sys.executable,
        "-I",
        "-B",
        "-c",
        BOOTSTRAP,
        str(root),
        str(TEST),
        "-q",
        "-k",
        selector,
        "--basetemp",
        str(root / f"pytest-{phase}"),
        "-p",
        "no:cacheprovider",
    ]
    environment = dict(os.environ)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    log = OUTPUT / f"mutation_{name}_{phase}.log"
    log.write_text(
        "COMMAND "
        + json.dumps(command)
        + "\n"
        + f"RETURN_CODE {result.returncode}\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
        encoding="utf-8",
    )
    return {"return_code": result.returncode, "log": str(log), "timeout_seconds": 30}


def main() -> None:
    initial_source = (SOURCE / MODULE).read_bytes()
    initial_test = (SOURCE / TEST).read_bytes()
    original = initial_source.decode("utf-8")
    outcomes: list[dict[str, object]] = []
    for case in CASES:
        assert original.count(case["original"]) == 1, case["name"]
        with tempfile.TemporaryDirectory(prefix=f"aef-mutation-{case['name']}-") as folder:
            root = Path(folder)
            shutil.copytree(
                SOURCE / "aef",
                root / "aef",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            (root / TEST).parent.mkdir(parents=True)
            (root / TEST).write_bytes(initial_test)
            (root / "pytest.ini").write_text("[pytest]\naddopts = --import-mode=importlib\n")
            baseline = run_case(root, case["name"], case["selector"], "baseline")
            assert baseline["return_code"] == 0, baseline
            (root / MODULE).write_text(
                original.replace(case["original"], case["replacement"]), encoding="utf-8"
            )
            mutated = run_case(root, case["name"], case["selector"], "mutated")
            assert mutated["return_code"] == 1, mutated
            outcomes.append(
                {
                    "name": case["name"],
                    "selected_regression": case["selector"],
                    "expected_test_count": case["expected_tests"],
                    "baseline": baseline,
                    "mutated": mutated,
                    "mutation_detected": True,
                }
            )
    # Scope this integrity check to the two inputs; unrelated source files may
    # change concurrently while other review agents finish their work.
    assert (SOURCE / MODULE).read_bytes() == initial_source
    assert (SOURCE / TEST).read_bytes() == initial_test
    output = {
        "source": str(SOURCE),
        "source_module_sha256": hashlib.sha256(initial_source).hexdigest(),
        "source_test_sha256": hashlib.sha256(initial_test).hexdigest(),
        "source_inputs_unchanged": True,
        "disposable_source_copies_only": True,
        "mutations": outcomes,
    }
    result_json = json.dumps(output, indent=2, sort_keys=True)
    (OUTPUT / "mutation_checks.json").write_text(result_json + "\n", encoding="utf-8")
    print(result_json)


if __name__ == "__main__":
    main()
