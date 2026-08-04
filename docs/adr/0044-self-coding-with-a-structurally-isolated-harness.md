# ADR 0044: Agents may author their own code; the harness is structurally isolated

## Status
Accepted (planning decision; no implementation yet). Supersedes ADR 0041.

## Context
Two things forced this decision.

**1. The palette design was substantially inert.** ADR 0041 bounded agents
to recombining human-reviewed components via a wiring manifest, on the
premise that edge/priority/condition edits redirect control flow. Review
disproved that premise: `GraphExecutor._resolve_route`
(`executor.py:233-260`) returns the route the **node** supplied; edges only
*authorize* it, and `priority` merely orders which authorizing edge is
inspected. Verified against the shipped example, which returns literal
`"search"`/`"summarize"`/`END` from node code
(`examples/hello_agent/graph.py:90,107,130`). **Routing lives in node
implementations.** A wiring-only agent can forbid a route, toggle HITL, or
change the node set — it cannot change what the agent does.

**2. The owner requires it.** The stated goal is agents that author new
code for themselves, with the owner's review-and-merge to `main` as the
only human gate.

Removing the palette removes the containment boundary ADR 0041 called "the
single most important safety property." Something must replace it, and the
replacement cannot be a check the candidate could influence — the Darwin-
Gödel Machine, self-modifying under sandboxing *and* human supervision,
removed the tool-use markers used to detect its own hallucinations
([sakana.ai/dgm](https://sakana.ai/dgm/),
[arXiv 2505.22954](https://arxiv.org/abs/2505.22954)). A self-modifying
agent that can reach its own detector will eventually reach it.

## Decision
**Agents may author code in Zone A only, and the harness that judges them
executes from a trusted ref they cannot write.**

Three zones:

| Zone | Contents | Agent writes? |
|---|---|---|
| A — Agent | `agents/<name>/**` — node implementations, wiring, prompts | ✅ |
| B — Harness | gate code, golden corpus, eval suite, CI workflow | ❌ |
| C — Kernel | `aef/**` | ❌ |

**The load-bearing mechanism:**

> Gates execute in CI **from the base ref (`main`)**, never from the branch
> under test. The candidate is `git diff main...branch`. Corpus, eval
> suite, and gate code are loaded from the base ref. A CI path allowlist
> restricts the branch diff to Zone A; any diff touching Zone B or C is
> rejected before any other gate runs.

The candidate is *input* to the harness and can never *be* the harness.
This is enforced by CI configuration, which lives in Zone B — not by a
check the candidate could alter.

Corollaries, all now mandatory rather than optional:
- **Sandboxed execution** — the agent runs code it wrote during validation:
  no credentials worth stealing, allowlisted egress, scratch-dir writes only.
- **Held-out corpus split** — train (proposer-visible) / validation (gate) /
  owner-only rotating holdout; `grounded_in` may cite train only.
- **Null-hypothesis control cohort** — a candidate must beat randomly
  mutated variants, not merely the incumbent
  ([arXiv 1902.07638](https://arxiv.org/abs/1902.07638)).
- **Diff-size budget** — a proposal too large for a human to genuinely
  review is auto-rejected, not surfaced. The owner's review is the primary
  control; a change that defeats reviewability defeats the control.
- **Post-merge monitoring + auto-rollback** — partial compensation for the
  absent shadow/canary evidence (ADR 0042 correction).

## Consequences
- Self-improvement becomes *possible* at all, which the palette design was
  not (see Context 1).
- **Owner review cost rises sharply.** A 400-line Python diff is far harder
  to review than a YAML diff. The diff-size budget bounds this; it does not
  solve it. This is the design's principal residual risk and is stated as
  such in `04-review-and-self-coding-redesign.md` Part 3.
- Reward-hacking likelihood moves from Low to **High** under self-coding
  (DGM is the existence proof), which is why the control cohort and
  held-out split are no longer deferrable.
- Zone B's integrity no longer depends on the agent honoring a rule. It is
  a property of where code executes.
- ADR 0043 (separation of powers) is *strengthened*: its rule is unchanged,
  but its enforcement moves from inspecting a diff to the trust boundary
  above, closing the enforcement gap review found (a branch editing the gate
  implementation would otherwise be judged by the edited gate).
- The evolution engine (`aef/evolution/`) remains disabled. This program
  does not enable unsupervised auto-promotion; the owner's merge is still
  the sole promotion gate (ADR 0042).

## Alternatives Considered
- **Keep the palette (ADR 0041).** Rejected: disproved premise — it
  constrains agents to the one surface that cannot change behaviour, so it
  buys safety by buying uselessness.
- **Allow code authoring but have the gates run from the branch.**
  Rejected: circular. A candidate that can modify its judge is not judged.
  This is the DGM failure mode exactly.
- **Allow code authoring with no human gate.** Rejected: the owner's review
  is the only control that catches *intent* rather than regression, and
  nothing in this design replaces it.
- **Static analysis alone instead of sandboxed execution.** Rejected:
  necessary but insufficient — validation must actually run the code, and
  running untrusted code without isolation is the vulnerability.

## Confidence
High on the trust-boundary mechanism: it is a structural property, not a
behavioural assumption, and it directly addresses the one documented
real-world failure of a comparable system. High on the premise correction
(verified in source). **Medium on whether the overall program is
worthwhile** — that depends on whether agent-authored changes outperform an
owner editing code directly, which is unknown and is why
`04-review-and-self-coding-redesign.md` §2.7 defines explicit kill criteria.
