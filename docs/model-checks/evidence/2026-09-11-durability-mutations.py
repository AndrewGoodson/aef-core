"""Run targeted durability mutants only in disposable copies of aef-core.

Usage: python -B aef-runtime-durability-mutations.py --source /path/to/aef-core
       --output /tmp/aef-durability-mutations
Original source files are read, hashed before/after, and never written here.
Run with the source repository's activated virtual environment. The output
directory must not already exist and must resolve outside the source tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
SOURCE = args.source.resolve()
OUTPUT = args.output.resolve()
if OUTPUT == SOURCE or SOURCE in OUTPUT.parents:
    parser.error("output must be outside the source repository")
if not (SOURCE / "aef" / "kernel" / "durability.py").is_file():
    parser.error("source must be an aef-core checkout")
OUTPUT.mkdir(parents=True, exist_ok=False)
TRACKED = (
    "aef/kernel/durability.py",
    "tests/kernel/test_durability.py",
    "tests/kernel/test_executor.py",
)
CRASH_TEST = (
    "tests/kernel/test_executor.py::test_resume_refuses_checkpoint_written_before_cursor_commit"
)
SHORT_TEST = "tests/kernel/test_durability.py::test_atomic_write_completes_short_writes"


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in TRACKED}


def run_case(name: str, replacement: tuple[str, str] | None, tests: list[str]) -> dict:
    root = OUTPUT / name
    shutil.copytree(
        SOURCE / "aef", root / "aef", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    (root / "tests" / "kernel").mkdir(parents=True)
    for relative in TRACKED[1:]:
        shutil.copyfile(SOURCE / relative, root / relative)
    shutil.copyfile(SOURCE / "pyproject.toml", root / "pyproject.toml")
    copied = root / TRACKED[0]
    if replacement is not None:
        old, new = replacement
        content = copied.read_text()
        assert content.count(old) == 1, f"{name}: mutation anchor must match exactly once"
        copied.write_text(content.replace(old, new))
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    provenance = subprocess.run(
        [sys.executable, "-B", "-c", "import aef.kernel.durability as d; print(d.__file__)"],
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
        *tests,
        "--disable-warnings",
        f"--basetemp={root / 'pytest-tmp'}",
    ]
    start = time.monotonic()
    completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    log = root / "pytest.log"
    log.write_text(completed.stdout + completed.stderr)
    return {
        "name": name,
        "cwd": str(root),
        "command": command,
        "loaded_module": provenance,
        "mutated_file_sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
        "exit_code": completed.returncode,
        "seconds": round(time.monotonic() - start, 3),
        "log": str(log),
        "summary": completed.stdout.strip().splitlines()[-1],
        "outcome": "baseline_passed"
        if replacement is None and completed.returncode == 0
        else "mutant_killed"
        if replacement is not None and completed.returncode == 1
        else "unexpected",
    }


before = hashes()
cases = [run_case("baseline", None, [CRASH_TEST, SHORT_TEST])]
cases.append(
    run_case(
        "sequence_check_removed",
        (
            "    if checkpoint_seq != latest_seq:\n",
            "    if False:  # disposable mutation: skip cursor binding check\n",
        ),
        [CRASH_TEST],
    )
)
cases.append(
    run_case(
        "short_write_truncation",
        (
            '        pending = memoryview(text.encode("utf-8"))\n'
            "        while pending:\n"
            "            written = os.write(fd, pending)\n"
            "            if written <= 0:\n"
            '                raise OSError(f"atomic write to {path} made no progress")\n'
            "            pending = pending[written:]\n",
            '        os.write(fd, text.encode("utf-8"))'
            "  # disposable mutation: ignore short write\n",
        ),
        [SHORT_TEST],
    )
)
after = hashes()
report = {
    "source": str(SOURCE),
    "interpreter": sys.executable,
    "script": str(Path(__file__).resolve()),
    "source_hashes_before": before,
    "source_hashes_after": after,
    "source_unchanged": before == after,
    "cases": cases,
    "all_expected": before == after and all(case["outcome"] != "unexpected" for case in cases),
}
report_path = OUTPUT / "report.json"
report_path.write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps(
        {
            "report": str(report_path),
            "all_expected": report["all_expected"],
            "cases": [
                {k: c[k] for k in ("name", "exit_code", "summary", "outcome")} for c in cases
            ],
        },
        indent=2,
    )
)
raise SystemExit(0 if report["all_expected"] else 1)
