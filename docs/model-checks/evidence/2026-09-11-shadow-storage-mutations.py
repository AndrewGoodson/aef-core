"""Check shadow checkpoint isolation using disposable copies of aef-core.

Run with the source checkout's activated virtual environment:
    python -B 2026-09-11-shadow-storage-mutations.py --source /path/to/aef-core \
        --output /tmp/aef-shadow-storage-mutations

The required output directory must be new and outside the source checkout.
Only disposable copies run tests or receive mutations. Original runtime and
test files are read and hashed before and after the experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

TRACKED = ("aef/harness/shadow.py", "tests/harness/test_promotion_safety.py")
TEST = (
    "tests/harness/test_promotion_safety.py::"
    "test_shadow_checkpoints_do_not_read_or_replace_the_incumbents_store"
)


def hashes(source: Path) -> dict[str, str]:
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in TRACKED}


def run_case(source: Path, output: Path, *, mutate: bool) -> dict[str, Any]:
    name = "shared_storage_mutant" if mutate else "baseline"
    root = output / name
    shutil.copytree(
        source / "aef", root / "aef", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    (root / "tests" / "harness").mkdir(parents=True)
    shutil.copy2(source / TRACKED[1], root / TRACKED[1])
    shutil.copy2(source / "pyproject.toml", root / "pyproject.toml")
    copied = root / TRACKED[0]
    if mutate:
        text = copied.read_text()
        original = "durability=_EphemeralDurability(),"
        assert text.count(original) == 1, "mutation anchor must match exactly once"
        copied.write_text(text.replace(original, "durability=base.durability,"))
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    provenance = subprocess.run(
        [sys.executable, "-B", "-c", "import aef.harness.shadow as s; print(s.__file__)"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(provenance).resolve() == copied.resolve(), provenance
    command = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        TEST,
        "--disable-warnings",
        f"--basetemp={root / 'pytest-tmp'}",
    ]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    log = root / "pytest.log"
    log.write_text(result.stdout + result.stderr)
    expected = 1 if mutate else 0
    lines = result.stdout.strip().splitlines()
    return {
        "name": name,
        "command": command,
        "cwd": str(root),
        "loaded_module": provenance,
        "copied_file_sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
        "exit_code": result.returncode,
        "expected_exit_code": expected,
        "matched_expected_exit": result.returncode == expected,
        "log": str(log),
        "summary": lines[-1] if lines else "no pytest stdout",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        parser.error("output must be outside the source repository")
    if not all((source / name).is_file() for name in TRACKED):
        parser.error("source must be an aef-core checkout containing the shadow regression")
    output.mkdir(parents=True, exist_ok=False)
    before = hashes(source)
    cases = [run_case(source, output, mutate=False), run_case(source, output, mutate=True)]
    after = hashes(source)
    expected = before == after and all(case["matched_expected_exit"] for case in cases)
    report = {
        "source": str(source),
        "script": str(Path(__file__).resolve()),
        "source_hashes_before": before,
        "source_hashes_after": after,
        "source_unchanged": before == after,
        "cases": cases,
        "all_expected": expected,
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "all_expected": expected}, indent=2))
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
