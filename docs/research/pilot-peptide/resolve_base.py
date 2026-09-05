"""L1 (ADR 0189) on a real `master` repo: which term of resolve_default_base_ref answers.

Arm 1 — the safety clone, whose `origin` was removed before anything ran, so
        term 1 (refs/remotes/origin/HEAD) cannot answer and term 2 (the branch
        HEAD is on) must.
Arm 2 — a clone OF that clone, which git gives an origin/HEAD, so term 1 answers.
        No remote in either arm can reach /Users/raptor/peptideindex.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from aef.harness.git import GitRepo
from aef.harness.loop import FALLBACK_BASE_REF, resolve_default_base_ref

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
CLONE = W / "peptide"
CLONE2 = W / "peptide-origin-probe"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    return (out.stdout or out.stderr).strip()


print(f"FALLBACK_BASE_REF (the literal used when the repo has no answer) = {FALLBACK_BASE_REF!r}")
print()

print("== arm 1: the safety clone (origin removed)")
print(f"   remotes:              {git(CLONE, 'remote') or '(none)'}")
_branches = git(CLONE, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
print(f"   branches:             {_branches}")
_origin_head = git(CLONE, "symbolic-ref", "refs/remotes/origin/HEAD")
print(f"   origin/HEAD:          {_origin_head or '(absent)'}")
print(f"   HEAD is on:           {git(CLONE, 'rev-parse', '--abbrev-ref', 'HEAD')}")
print(f"   resolve_default_base_ref -> {resolve_default_base_ref(GitRepo(CLONE))!r}")
print()

if not CLONE2.exists():
    subprocess.run(["git", "clone", "-q", str(CLONE), str(CLONE2)], check=True)
print(
    "== arm 2: a clone of the clone (git writes origin/HEAD; "
    "origin is the CLONE, not the real repo)"
)
print(f"   origin url:           {git(CLONE2, 'remote', 'get-url', 'origin')}")
print(f"   origin/HEAD:          {git(CLONE2, 'symbolic-ref', 'refs/remotes/origin/HEAD')}")
print(f"   resolve_default_base_ref -> {resolve_default_base_ref(GitRepo(CLONE2))!r}")
print()

ok = (
    resolve_default_base_ref(GitRepo(CLONE)) == "master"
    and resolve_default_base_ref(GitRepo(CLONE2)) == "master"
)
print(f"both terms answer 'master', and neither is the fallback literal: {ok}")
sys.exit(0 if ok else 1)
