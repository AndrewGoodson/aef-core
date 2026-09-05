"""L1 (ADR 0189) on the OWNER'S OWN checkout — read-only.

This is the case the clone could not exercise: a repository with a real
`origin`, currently checked out on `aef/adopt` (not `master`), so term 1
(refs/remotes/origin/HEAD) and term 2 (the branch HEAD is on) disagree and
the order matters. Nothing here writes.
"""

from __future__ import annotations

from pathlib import Path

from aef.harness.git import GitRepo
from aef.harness.loop import FALLBACK_BASE_REF, resolve_default_base_ref

repo = GitRepo(Path("/Users/raptor/peptideindex"))
print("== /Users/raptor/peptideindex (the owner's checkout, read-only)")
print(f"   origin/HEAD                 : {repo.symbolic_ref('refs/remotes/origin/HEAD')}")
print(f"   HEAD is on                  : {repo.symbolic_ref('HEAD')}")
print(f"   FALLBACK_BASE_REF           : {FALLBACK_BASE_REF!r}")
print(f"   resolve_default_base_ref -> : {resolve_default_base_ref(repo)!r}")
print()
print("   term 1 answers, and it answers 'master' while HEAD is on 'aef/adopt' —")
print("   which is the property ADR 0189 gives as term 1's reason: the default")
print("   does not move when the operator checks something else out.")
