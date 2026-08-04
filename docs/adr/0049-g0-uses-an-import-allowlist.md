# ADR 0049: G0 uses an import allowlist; the pipeline imposes its own order

## Status
Accepted. Implements M3 (gates G0, G1, G4) of the self-rewiring roadmap.

## Context
With self-coding (ADR 0044), agents author Python in Zone A. The zone and
mode checks from M1 constrain *where* code lands and *what kind of object*
it is; neither says anything about what the code does once it runs.

Three decisions here, plus one correction carried forward from the
three-reviewer audit.

## Decision

**1. Imports are governed by an allowlist, not a denylist.** A denylist has
to anticipate every escape — `subprocess`, `ctypes`, `importlib`, `socket`,
`pickle`, `marshal`, and whatever the next release adds. An allowlist only
has to describe what an agent legitimately needs, and anything novel is
denied by having been *left out* rather than by having been foreseen. This
is constraint #6's deny-by-default applied to code rather than to tools.

Vendor isolation (constraint #3) falls out for free: `anthropic`, `openai`,
`mem0`, and `neo4j` are simply not on the list, so agent-authored code
cannot import them wherever it sits — no second enforcement mechanism, no
second thing to keep in sync with `tests/test_vendor_isolation.py`.

Relative imports are permitted: they cannot leave Zone A.

**2. G1 runs against a constructed post-merge workspace, never a checkout.**
`build_candidate_workspace` materialises the base-ref tree and overlays the
candidate's **Zone A files only** — exactly the repository state after this
candidate merges. `git checkout <branch>` would run the branch's harness,
which is the thing ADR 0047 exists to prevent. The overlay loop re-checks
every path and **raises** on anything not Zone A, so the trust boundary
holds even if an upstream zone check has a bug.

**3. G4 checks safety metadata, because no path check can see it.** With
agents authoring `Node(...)` and `Edge(...)` calls, each safety declaration
is load-bearing for a control elsewhere in the kernel. G4 rejects the
combinations that disable a control *while looking ordinary*:
`deterministic=True` alongside non-pure `side_effects` (replay would repeat
the I/O), a constant-returning `idempotency_key_fn` (dedup collapses), an
agent-declared `fallback_node_id` (swallows errors and makes replay trust
the record verbatim), and `requires_human_approval=False` /
`requires_deterministic_fallback=False`.

Note what is *not* forbidden: an agent may need a fallback. The gate targets
the disabling combination, not the feature.

**4. The pipeline imposes the canonical order itself.** `run_pipeline`
sorts by `CANONICAL_ORDER` rather than trusting the caller's list, so no
caller can — accidentally or otherwise — schedule G2's expensive corpus run
before the cheap gate that would have rejected the candidate outright. An
**empty pipeline does not count as passing**: "no gates ran" must never read
as "the candidate passed".

**5. G1 drops the reachability checks** the superseded spec required.
Routing is chosen by node code, not authorised by edges, so `END` never
appears in an `Edge` and END-reachability is undecidable from the edge set;
node reachability additionally produces false positives, because
`fallback_node_id` targets bypass edge resolution (ADR 0036) and a correctly
wired fallback-only node would look like an orphan. Recorded here because
the check *looks* obviously correct and will be proposed again otherwise.

## Consequences
- Every gate ships with its known-bad case; 53 tests. A gate that cannot
  reject is not a gate.
- The ordering property is asserted directly: gates supplied as
  `[G3, G2, G4, G1, G0]` execute as `G0, G1, G4, G2, G3`.
- Fail-fast is tested by observing that later gates never ran — a
  subverting candidate is stopped by G0 and never reaches G1's expensive
  build.
- The diff-size budget (Q-A1, owner default: 200 lines / 3 files) is
  enforced by G0 and overridable per run via `GateContext.limits`. It is
  deliberately restrictive; loosen only with evidence.
- **G0 reads file contents from the HEAD ref, not the working tree**, so an
  uncommitted local edit cannot make a candidate look clean.
- **Not implemented: G5, G2, G3.** They are in `CANONICAL_ORDER` but
  unregistered, so the pipeline simply does not run them yet. A candidate
  passing today's pipeline has **not** been checked for behavioural
  regression, and must not be auto-merged — Tier 1 requires all of them
  (ADR 0045).

## Alternatives Considered
- **Denylist of dangerous imports.** Rejected: it fails open on anything
  unanticipated, and the set of dangerous stdlib modules is not closed.
- **Running the candidate branch directly in a container.** Rejected: the
  container bounds the blast radius but does not stop the branch's own
  harness from being the thing that judges it. Isolation and trust boundary
  are different problems; this milestone needs both, and the workspace is
  what provides the second.
- **Executing agent code to inspect its metadata** (importing the module
  and reading `Node` objects). Rejected outright: G4 would then run the code
  it is judging, before G1 has established the code is even safe to run.
  AST inspection never executes.
- **Treating `fallback_node_id` as merely advisory.** Rejected: it silently
  converts a crash into a route *and* changes replay semantics, which is two
  controls, not one.

## Confidence
High on the allowlist and the pipeline ordering — both are directly tested,
including the negative cases. High on the workspace construction, which has
a test proving a Zone B edit cannot reach the tree gates run against.
Medium on G4's metadata scan: AST matching recognises `Node(...)` and
`Edge(...)` **by name**, so a candidate aliasing the import
(`from aef.kernel import Node as N`) would evade it. That is a real,
known gap — the mitigation today is that such a candidate must still pass
G0's allowlist and G1's suite, and the eventual fix is resolving names
rather than matching them. **Not claimed:** that static analysis alone
establishes an agent-authored change is safe. It establishes only that the
change is not obviously unsafe; behavioural assurance is G2/G3's job and
neither exists yet.
