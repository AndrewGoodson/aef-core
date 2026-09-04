# ADR 0147: `bless` must archive the tree that contains the agent

## Status
Accepted. Increment L5 of `INGEST_LOOP.md`; record in `IMPROVE_LOG.md`.
**No rubric dimension moves.** It closes the first of the two defects ADR
0139 found from the adopter's side and reported rather than fixed (the second
was `.gitignore`, closed by ADR 0142).

## Context

`bless` asks one question and answers a different one:

```python
if not repo.path_exists_at(ref, agent_path):     # does the agent exist?
    raise BlessError(...)
files = _zone_a_files(repo, ref, agent_root)     # what gets archived?
```

Nothing checked that the second contains the subject of the first, and the
printed message names the first while doing the second.

### Reproduced first, RUN

The shape ADR 0139 hit: a repo where `aef migrate` wrote its module to the
repo root (Zone C) and Zone A holds only the `agents/README.md` that
`aef adopt` writes.

```
$ git ls-tree -r --name-only HEAD -- agents
agents/README.md

$ aef loop bless --repo . --state k3-state --agent-path aef_migrated.py
blessed aef_migrated.py as baseline v1 for graph 'default'
  G5 now has a reference point to measure drift against.            exit=0

$ find k3-state/archive -type f
k3-state/archive/default/v000001/entry.json
k3-state/archive/default/v000001/files/agents/README.md

$ jq .file_digests k3-state/archive/default/v000001/entry.json
{ "agents/README.md": "9aac3d63..." }
```

**A green message naming a file the archive does not contain.** The
consequence is not cosmetic and it compounds twice:

1. The `blessed baseline` obligation goes green on evidence unrelated to the
   agent, so `aef loop doctor` reports the loop ready when the baseline is a
   README.
2. G5 measures every candidate's `structural_drift` against that baseline.
   `structural_drift` unions the two key sets, so the first real candidate —
   whose side describes the whole Zone A tree including the agent — is
   charged for the agent's entire existence as an addition. This is exactly
   the arithmetic of ADR 0074, arriving from the other side: that fix made
   both sides read the same tree, and nothing stopped an owner from blessing
   a *different* tree in the first place.

## Decision

**Refuse when the agent path is not inside the tree that would be archived,
naming both paths.** The check goes after the existence check and after the
empty-tree check, because "the agent is not committed" and "Zone A is empty"
are different problems with different remedies:

```
error: aef_migrated.py exists at HEAD but is NOT inside the tree this would
archive: 'agents' at HEAD holds 1 file(s) (agents/README.md). A baseline is
the whole Zone A tree, and G5 measures every candidate's drift against it, so
blessing here would report aef_migrated.py as blessed while archiving a tree
that does not contain it. Move the agent under 'agents' (Zone A is the only
place the loop may propose changes), or pass --agent-root naming the tree
aef_migrated.py actually lives in.
```

Both remedies are real and the owner picks: Zone A is where the loop is
allowed to propose, and `--agent-root` already exists for a repo that puts it
elsewhere.

Three details, each deliberate:

- **The tree is named through `agent_root`, never spelled.** `bless` already
  defaults it from `zones.DEFAULT_AGENT_ROOT`, and the message interpolates
  the parameter, so a repo that moves its agent root gets a message about its
  own tree. `aef/cli/loop.py`'s `DEFAULT_AGENT_PATH` — the last place in that
  file that spelled `agents` — is built from `DEFAULT_AGENT_ROOT` too.
- **Path spellings are normalised** (`./agents/graph.py` and
  `agents/graph.py` are one answer). Git reports the second; a person types
  either, and a refusal that fires on a spelling teaches owners to distrust
  the check.
- **The `no files under <root>` branch stops being `pragma: no cover`.** Its
  comment claimed "agent_path is inside agent_root in practice", which was
  the assumption this defect lived inside. It is reachable and it is now
  covered by the same test that reaches the new refusal's sibling case.

`aef migrate` writing into Zone A (L1, ADR 0143, another worker) makes this
harder to reach and does not fix it: a repo that migrated before that change,
or an owner who passes `--agent-path` by hand, arrives here unchanged.

## Evidence

```
$ aef loop bless --repo . --state k3-state --agent-path aef_migrated.py
error: aef_migrated.py exists at HEAD but is NOT inside the tree this would
archive: 'agents' at HEAD holds 1 file(s) (agents/README.md). ...    exit=1

$ find k3-state/archive -type f
<nothing>
```

Nothing archived, so the obligation stays red rather than going green on the
wrong tree — asserted by the test through `archive.versions(...) == ()`
rather than through the printed line.

The control, run in the same sequence that closes L3: `bless --agent-path
agents/mine/graph.py` on a repo whose graph *is* under Zone A still prints
`blessed agents/mine/graph.py as baseline v1` and the cycle then gates a
candidate against it (ADR 0145's Evidence).

**Mutations** (planted with the L3 round, 85-test baseline, each restored
from a byte-identical backup verified by SHA-1):

```
M7  the containment check is removed             1 failed, 84 passed
      -> test_bless_refuses_an_agent_path_outside_the_tree_it_would_archive
M8  containment compares raw strings             1 failed, 84 passed
      -> test_bless_accepts_the_same_file_spelled_with_a_leading_dot_slash
M10 the empty-Zone-A refusal is folded in        1 failed, 84 passed
      -> test_bless_refuses_when_zone_a_is_empty
```

M8 is the control on the fix itself: a containment check that is too strict
refuses a correct blessing, which is the failure mode a hastily written
version of this would have shipped. M10 pins the distinction the new refusal
must not swallow — "you have no Zone A" and "your agent is somewhere else"
have different remedies.

**Green bar** (shared with ADR 0145): `pytest -q` 1960 passed, 1 skipped
(from 1945; +15); `mypy aef examples` 129 files clean; `ruff check .` clean;
`ruff format --check aef tests examples` 239 formatted. Zero model calls.

## Consequences

- **The `blessed baseline` obligation can no longer go green on a tree that
  does not contain the agent**, and G5's drift budget is measured against
  something that contains what it is measuring.
- **An adopter who migrated to the repo root now gets a refusal instead of a
  false success**, which is the right way round: the refusal names the two
  actions that fix it, and the false success named neither.
- **`--agent-root` acquires a second reason to exist.** It was there so a
  repo could move Zone A; it is now also the answer this refusal points at.

## Confidence

**High** that the defect is closed for the shape ADR 0139 reproduced: the
same command, on the same repo shape, refuses and archives nothing, and the
mutation removing the check fails the test.

**Medium** on completeness. The check compares an agent path against the file
list of one tree at one ref; a symlink inside Zone A pointing outside it, or
a path that resolves differently on a case-insensitive filesystem, was not
tested. Neither arises from `git ls-tree` output, which is where both sides
come from, but neither was run.

**Not measured:** whether any real repo has ever blessed a wrong tree and is
carrying a mis-measured drift budget today. Nothing detects that
retroactively; re-blessing is rate-limited and owner-only by design (G5, ADR
0053), so an owner who suspects it has to look at the archive.
