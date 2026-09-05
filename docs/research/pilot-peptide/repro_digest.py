"""F-N7-2. `aef loop digest`'s "Scenarios added to the corpus" is a constant 0,
and ADR 0190's new warning is keyed off it. Zero live model calls.

The pilot's own digest says

    - Production runs recorded: 5
    - Scenarios added to the corpus: 0
    **5 recorded, 0 admitted to the corpus.** ... one is not: `REJECTED, did
    not re-execute deterministically` on every run means the ingestion path is
    broken, not quiet.

on a day when `aef loop harvest` admitted all five, minutes earlier, into the
corpus in this repository. Three arms, one variable each, all through the real
CLI.
"""

from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from pathlib import Path

from aef.harness import loop as L
from aef.harness.corpus import load_corpus
from aef.harness.monitoring import build_digest

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
AEFSRC = "/Users/raptor/aef-core/.claude/worktrees/agent-a55b5aa3dfc315f8b"
CORPUS = W / "peptide" / "corpus"

DIGEST = [
    "/Users/raptor/aef-core/.venv/bin/python", "-W", "ignore::RuntimeWarning",
    "-m", "aef.cli.main", "loop", "digest",
    "--repo", ".", "--state", str(W / "state"),
    "--runs", str(W / "runs2"),
    "--agent-root", ".claude/agents",
    "--graph-id", "price-freshness-reviewer",
]
ENV = {"PYTHONPATH": AEFSRC, "PATH": "/Users/raptor/aef-core/.venv/bin:/usr/bin:/bin"}


def run(extra: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        DIGEST + extra, cwd=W / "peptide", env=ENV, capture_output=True, text=True, check=False
    )
    return p.returncode, (p.stdout + p.stderr)


corpus = load_corpus(CORPUS)
by_source: dict[str, int] = {}
for s in corpus.scenarios:
    by_source[str(s.source)] = by_source.get(str(s.source), 0) + 1
print(f"the corpus in this repository: {len(corpus.scenarios)} scenario(s), "
      f"by source {json.dumps(by_source, sort_keys=True)}")
print()

print("== arm 0 — can the command be TOLD which corpus to look at?")
rc, out = run(["--corpus", "corpus"])
print(f"   `aef loop digest ... --corpus corpus` -> EXIT={rc}")
print(f"   {out.strip().splitlines()[-1]}")
print()

print("== arm 1 — does anything compute the number?")
src = inspect.getsource(L.digest)
print(f"   'scenarios_added' appears in aef.harness.loop.digest's body : "
      f"{'scenarios_added' in src}")
print(f"   'corpus' appears in it                                      : "
      f"{'corpus' in src}")
print(f"   build_digest's default for scenarios_added                  : "
      f"{inspect.signature(build_digest).parameters['scenarios_added'].default}")
print()

print("== arm 2 — the same command, corpus present vs corpus emptied")


def digest_lines(out: str) -> tuple[str, bool]:
    line = next(ln for ln in out.splitlines() if "Scenarios added to the corpus" in ln)
    return line.strip(), "5 recorded, 0 admitted to the corpus" in out


rc_full, out_full = run([])
line_full, warn_full = digest_lines(out_full)

backup = W / "corpus-backup"
if backup.exists():
    shutil.rmtree(backup)
shutil.copytree(CORPUS, backup)
try:
    for f in (CORPUS / "train").glob("*.json"):
        f.unlink()
    (CORPUS / "manifest.json").write_text('{"scenarios": {}}\n')
    assert not list((CORPUS / "train").glob("*.json")), "corpus was not emptied"
    rc_empty, out_empty = run([])
    line_empty, warn_empty = digest_lines(out_empty)
finally:
    shutil.rmtree(CORPUS)
    shutil.copytree(backup, CORPUS)

restored = load_corpus(CORPUS)
print(f"   5 harvested scenarios present : {line_full}   (ADR 0190 warning printed: {warn_full})")
print(f"   corpus emptied to 0           : {line_empty}   (ADR 0190 warning printed: {warn_empty})")
print(f"   identical                     : {(line_full, warn_full) == (line_empty, warn_empty)}")
print(f"   corpus restored               : {len(restored.scenarios)} scenario(s), "
      f"{sum(1 for s in restored.scenarios if str(s.source) == 'harvest')} from harvest")
