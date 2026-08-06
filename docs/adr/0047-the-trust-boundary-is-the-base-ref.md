# ADR 0047: The trust boundary is the base ref, not the zone check

## Status
Accepted. Implements M1 of the self-rewiring roadmap. Realises the
structural isolation ADR 0044 specified.

**Implementation correction (2026-08-06):** the original decision text said
every gate, corpus, suite, and workflow byte was loaded through
`BaseRefHarness`. That is not the integrated call path. The loop imports its
gates from the already-running AEF package; `BaseRefHarness` is an explicit
base-ref read/materialisation utility. The supplied workflows establish the
property at launch by checking out and installing trusted `main`, then fetching
the candidate only as data. A local caller running AEF from a candidate-altered
checkout is not structurally protected by `BaseRefHarness`. The decision and
confidence below are narrowed accordingly.

## Context
ADR 0044 established that self-coding is survivable only if the harness is
structurally isolated from the candidate: *"if an agent can modify what
judges it, the judgement carries no information."* It did not say by what
mechanism.

The obvious mechanism is a path allowlist — reject any diff touching gate
code. That is necessary but **not sufficient**, and relying on it is the
failure mode the Darwin-Gödel Machine demonstrated: DGM removed its own
hallucination detectors while sandboxed and under human supervision
([arXiv 2505.22954](https://arxiv.org/abs/2505.22954)). A check that must
*notice* an attack fails open the moment it has a bug or a gap.

Building it surfaced three escapes invisible to any path classifier, each
confirmed against real git rather than reasoned about from documentation.

## Decision

**1. The boundary is "the executing harness has trusted provenance", not
"reject Zone B diffs".** In the supplied CI workflows, AEF is checked out and
installed from `main`; only after that is the candidate fetched under a data
ref. The candidate workspace is reconstructed from Git objects and is never
used as the source of gate imports. This is the integrated boundary.

`BaseRefHarness` resolves explicit Zone B reads via
`git show <base_sha>:<path>`. It proves that a caller can pin and execute a
base-ref gate even when the checked-out branch rewrites that file. It does
**not** mediate all reads made by `aef loop gate`, and it cannot repair an
untrusted launcher that imports AEF from the candidate checkout.

The zone check remains, demoted to what it is good at: a **signal**. A Zone
B diff is a security event worth halting on (`05-approval-policy.md` §6),
not the thing standing between the candidate and the judge.

`BaseRefHarness.read()` **refuses any non-Zone-B path.** If this API would
load Zone A, "gates run from the base ref" degrades into "gates run from
wherever the caller asked". Candidate content is read through a
deliberately different module, `candidate.py`.

**2. `--no-renames` is a security flag.** With git's rename detection on,
`git mv aef/kernel/executor.py agents/executor.py` reports **only the
destination** — one Zone A path — while deleting a kernel file. Verified
directly: the Zone C path vanishes from `--name-only` output entirely.
`--no-renames` reports the delete and the add separately. `-z` is likewise
required, or git quotes paths containing spaces or newlines and naive
parsing mis-slices them.

**3. Blob modes are checked, because paths cannot see them.** Three escapes
present as valid Zone A paths:
- **symlink** (mode `120000`): `agents/link -> ../aef/kernel/executor.py`
  passes every string test; writing through it lands in Zone C.
- **submodule/gitlink** (`160000`): a Zone A path pulling an arbitrary
  external tree.
- **executable bit** (`100755`): a privilege the agent has no need for.

Only `100644` (and `000000`, a deletion) may land. Symlinks and submodules
are **security events**; the executable bit is an ordinary rejection. Even a
symlink *within* Zone A is refused — resolving link targets is a game the
harness declines to play.

**4. The sandbox declares its capabilities and refuses to overstate them.**
It genuinely enforces: environment scrubbed to an allowlist, `cwd` confined,
wall-clock timeout killing the whole process group (`setsid`), and POSIX
rlimits. It **cannot** enforce network egress (a process cannot revoke its
own connectivity), filesystem confinement (`cwd` is a default, not a jail),
or an exact child environment (macOS injects `__CF_USER_TEXT_ENCODING`
after `execve` — found by a failing test, not anticipated).

So `SandboxPolicy` **raises at construction** unless network isolation is
attested by the layer that can actually provide it, and every
`SandboxResult` carries a `SandboxCapabilities` record of what was really
in force. Attestation is passed in rather than read from the environment,
so its value comes from Zone B config, not from anything a candidate sets.

**5. Zone A is `agents/**` in the adopting repo; `aef/**` has no carve-out.**
Adopted as the owner default (reversible). `aef/agents/` stays non-writable:
the exclusion's value is that it is a whole subtree with no exceptions to
reason about. Zone B is **not configurable at all** — the adopting repo may
say where its agents live, never where its gates live. Enforced by a test
asserting `ZonePolicy` has exactly one field.

## Consequences
- The explicit-read primitive is directly tested:
  `test_a_candidate_that_rewrites_its_gate_still_faces_the_original_gate`
  builds a real repo, commits a subverted gate on the branch, loads the
  base-ref gate, **executes it**, and asserts it still rejects.
- The supplied CI workflows make trusted launch provenance inspectable: they
  check out `main`, install it, and fetch the candidate as data. Real-Git tests
  cover the explicit read and candidate reconstruction primitives.
- Deny-by-default extends to malformed paths: traversal, absolute,
  backslash, null byte, and case variants are all security events, since
  none can arise from a well-formed `git diff`.
- **Locally, the sandbox runs unisolated or not at all.** That is
  deliberate friction. CI must supply container-level isolation and attest
  it; until then, results honestly record `network_isolated=False`.
- **Local limitation:** the package cannot attest its own import provenance.
  Running `aef loop gate` from a candidate-modified checkout forfeits this
  structural isolation even though Zone B classification still rejects the
  candidate diff.

## Alternatives Considered
- **Path allowlist as the primary control.** Rejected: it must *notice* an
  attack to stop one, and DGM is the existence proof that supervision plus
  sandboxing does not prevent a system from disabling its own detectors.
  Retained as a signal, not as the boundary.
- **Materialising all harness code through `BaseRefHarness`.** The primitive
  supports this, but the integrated loop does not use the materialised tree as
  its import root. The supplied workflow instead obtains equivalent execution
  provenance by checking out and installing trusted `main`.
- **Resolving symlink targets and allowing intra-Zone-A links.** Rejected:
  correct resolution requires modelling the whole tree at merge time, and
  every subtlety is an escape. Refusing all symlinks costs the agent
  nothing it needs.
- **Best-effort network blocking (e.g. clearing proxy vars, seccomp).**
  Rejected: partial measures produce a claim of isolation without the
  substance, and the claim is what downstream decisions trust. Refusing to
  run is more useful than a sandbox that quietly leaks.
- **Reading the isolation attestation from an env var inside the sandbox
  module.** Rejected: untestable, and it would put a security-relevant
  input somewhere closer to the candidate.

## Confidence
High that the supplied workflows execute the installed `main` package and
fetch the candidate as data, and high on the explicit base-ref read primitive.
No claim is made that arbitrary local launchers have trusted provenance.
High that the sandbox's declared capabilities match its enforcement. Medium on
the completeness of Git edge-case handling: real-repository tests now cover
attributes, unusual config, symlinks, submodules, modes, ignored files, and
workspace overlays, but absence of further edge cases is not claimed.
