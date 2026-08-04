# 04 — Review findings and the self-coding redesign

**Status:** planning artifact. Supersedes the palette-bounded design in
`01-architecture.md` and the gate specs in `gates/`, which are retained for
provenance but must be read through this document.

**Method:** three independent reviewers — one benchmarking against
Anthropic's published guidance, one against graph-engineering and
optimizer literature, one adversarial critic verifying ~40 code citations.
Two findings independently converged; one invalidated the design's premise.

---

## Part 1 — What the review found

### 1.1 Premise-invalidating: edges do not route; nodes do

`GraphExecutor._resolve_route` (`executor.py:233-260`) receives the route
**from the node** and only ever returns that same route. Edges
**authorize** a route (or raise `RoutingViolationError` /
`HumanApprovalRequiredError`); `priority` only orders which authorizing
edge is inspected first. Verified directly, plus the shipped example
returns literal `"search"` / `"summarize"` / `END` from node code
(`examples/hello_agent/graph.py:90,107,130`).

**Consequence.** A wiring-only manifest edit can: forbid a route, toggle
HITL, change the node set, change `entry_node`. It **cannot redirect
control flow.** Routing logic lives inside node implementations.

The palette-bounded design in `01-architecture.md` was therefore
*substantially inert* for real self-improvement: it constrained agents to
the one surface that cannot change what the agent does. G2's flagship
known-bad test — "flip an edge priority so routing changes"
(`gates/G2 §8.2`, `03-roadmap` M4, billed as *"the proof that the gate does
what replay could not"*) — **is not constructible in this kernel.**

**This is why self-coding is the correct scope**, not scope creep: in
aef-core, meaningful self-improvement requires changing node code.

### 1.2 `params` does not exist

`grep params aef/kernel/` returns **zero hits**. `Node`
(`contracts.py:192-202`) and `Context` (`104-131`) have no params field.
The manifest sketch's `params:` channel — the main tunable surface in
`01-architecture.md` §2 and the injection channel conceded in `gates/G0`
§4 — was a fiction. Implementing it would edit `aef/kernel/contracts.py`,
which this plan's own G4 protects.

### 1.3 The gate pipeline admitted only no-ops (found independently, twice)

`gates/G2` §3 passes only if **100%** of scenarios reproduce the *same
routing path* and equivalent final state; `gates/G3` §1 states the corpus
and eval suite are the same scenario set. So any candidate that moves an
`EvaluationRecord` fails G2 first — **G3's rules 1–3 can never fire**, and
its test 5 ("genuinely improves ⇒ accept") is unreachable.

This is also the exact anti-pattern Anthropic names twice: *"evaluate
whether it achieved the correct final state"*
([multi-agent, 2025-06-13](https://www.anthropic.com/engineering/multi-agent-research-system))
and *"grade what the agent produced, not the path it took"* — path-grading
yields "overly brittle tests"
([demystifying evals, 2026-01-09](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).

### 1.4 G4 was vacuous against its stated candidate type, and unenforced against the real threat

`01-architecture.md` §4.3 defines a candidate as a *manifest diff*, which
by construction cannot touch corpus paths — so G4 checked something that
could not happen. Meanwhile the actual threat (an agent with repo write
access on a branch) was never modeled: **nothing said gates run from a
trusted checkout.** A branch that edits the gate implementation would be
judged by the edited gate. Circular.

### 1.5 No held-out anything

The "design economy" of one corpus feeding G2 and G3 makes
**train = validation = test**. GEPA's central mechanism is the opposite —
selection on a held-out set never shown to the reflector
([arXiv 2507.19457](https://arxiv.org/abs/2507.19457)); DSPy warns prompt
optimizers overfit small train sets
([DSPy optimization overview](https://dspy.ai/learn/optimization/overview/)).
Worse, the proposer is grounded in `EvaluationRecord`s from the corpus it
is scored on — direct leakage.

### 1.6 Deferring the null-hypothesis baseline contradicted the plan's own principle

`03-roadmap.md` states the sequencing principle *"build the judge before
the judged"*, then defers the control baseline past M8 (the proposer). The
control baseline **is** part of the judge. Li & Talwalkar show random
search matches leading NAS methods
([arXiv 1902.07638](https://arxiv.org/abs/1902.07638)) — gains without a
control are unattributable. AlphaEvolve reports reward hacking as
*frequent* ([arXiv 2506.13131](https://arxiv.org/abs/2506.13131)).

### 1.7 Small-N: "beats or ties" is not a statistical claim

At n≈20 with binary `passed`, McNemar has near-zero power; bootstrap
half-widths run ~±20pp. `gates/G3` rules 2 and 4 are noise indicators, not
gates. Only rule 1 (zero-tolerance per-scenario regression) is meaningful,
and it is a deterministic assertion rather than a statistic. Nothing
controlled multiplicity: many candidates tested against one fixed corpus
([Miller, arXiv 2411.00640](https://arxiv.org/abs/2411.00640)).

### 1.8 Confirmed overclaims (now corrected)

| Claim | Verdict |
|---|---|
| "Agents cannot author new behaviour" (ADR 0041) | **False.** Corrected to "cannot author new *code*" — and now obsolete entirely, since self-coding is the new scope. |
| "Strictly stronger than criterion 7" (ADR 0042) | **False.** Broader in authority, **weaker in evidence**: no signed release manifests, no shadow execution against the real traffic distribution, no canary; post-merge the change is 100% live and rollback needs a process reload — the cold start criterion 6 forbids. |
| R3 likelihood "Low" | Unsupported as stated. Conditional: Low for a rule-based proposer, **High** for an LLM-backed or self-coding one (DGM hacked its own detector *under* human supervision and sandboxing — [sakana.ai/dgm](https://sakana.ai/dgm/), [arXiv 2505.22954](https://arxiv.org/abs/2505.22954)). |

### 1.9 Other confirmed defects (carried into the redesign)

- Gate ordering contradicted across three documents (diagram says
  G2→G3→G4; README rationale and M3 say G4 first).
- Owner-only field list incomplete: `idempotency_key_fn` (swap to a
  constant ⇒ dedup defeated), `fallback_node_id` (an added fallback
  swallows errors *and* makes replay trust records verbatim,
  `replay.py:52`), `requires_deterministic_fallback` (clearing it silences
  the emergent-routing marker).
- G1's END-reachability is **not computable** — `END` never appears in
  edges; it is returned by node code. Fallback targets bypass edge
  resolution, so a fallback-only node is falsely flagged an orphan.
- G3's cost gate is unmeasurable under pinned fixtures: `cost_tokens` is
  the recorded value by construction.
- M2's acceptance is unachievable: `Graph→manifest` extraction cannot name
  anonymous callables, and `hello_agent` uses
  `idempotency_key_fn=lambda state: state.run_id` (`graph.py:141`).
- No palette content-pinning: a ref is a *name*; its body changes under
  ordinary human PRs, so M6's "rollback restores an exact prior manifest"
  restores one whose meaning silently changed.
- Missing throughout: loop observability / proposal ledger, concurrency &
  staleness (two candidates gated against the same incumbent), the
  validation report as a prompt-injection channel into the human, unbounded
  owner load, corpus↔node-identity migration, and no post-merge monitoring.

---

## Part 2 — The self-coding redesign

**Owner decision:** agents may author new code for themselves, not merely
recombine reviewed components. Given §1.1, this is also the only scope in
which self-improvement is meaningful in this kernel.

### 2.1 Three zones, unequal trust

| Zone | Contents | Agent may write? |
|---|---|---|
| **A — Agent** | `agents/<name>/**` — node implementations, wiring, prompts | ✅ yes |
| **B — Harness** | gate code, golden corpus, eval suite, CI workflow | ❌ **never** |
| **C — Kernel** | `aef/**` — the scaffold and its guarantees | ❌ never |

### 2.2 The load-bearing mechanism: the harness runs from a trusted ref

The palette is gone, so containment must come from somewhere else. It comes
from **where the judgment executes**:

> **Gates execute in CI from the base ref (`main`), never from the branch
> under test. The candidate is `git diff main...branch`. Corpus, eval
> suite, and gate code are loaded from the base ref. A CI path allowlist
> restricts the branch's diff to Zone A; any diff touching Zone B or C is
> auto-rejected before any other gate runs.**

This closes §1.4 structurally. The candidate is *input* to the harness and
can never *be* the harness. It is enforced by CI configuration — which
lives in Zone B — not by a check the candidate could influence.

**This single property is what makes self-coding survivable.** Without it,
Zone B is protected only by hope.

### 2.3 Why this matters more now, not less

The DGM precedent is directly on point: a self-modifying, sandboxed,
human-supervised system removed the tool-use markers used to detect its own
hallucinations — it hacked its own detector while a human watched. The
lesson is not "don't do this"; it is **"the detector must not be in the
agent's write scope."** That is exactly §2.2.

### 2.4 Redesigned gates

| Gate | Definition (revised) |
|---|---|
| **G0 · Zone + static safety** | Path allowlist (Zone A only); import allowlist (preserves vendor isolation, constraint #3); no `eval`/`exec`/dynamic import; no new subprocess/network/filesystem escapes; **diff-size budget** — a proposal too large for a human to genuinely review is auto-rejected, not surfaced |
| **G1 · Builds** | Loads, `Graph.compile()`/`validate()`, `mypy --strict` clean, and the **existing test suite passes** (321 tests). Drops the uncomputable END-reachability check (§1.9) |
| **G2 · Outcome non-regression** | **Not path identity.** For every scenario that previously *passed*: it must still pass — same outcome class (`plan.status`, no new `errors`, no policy/HITL bypass). **Routing divergence is reported to the owner, never auto-rejected.** Previously-failing scenarios may diverge freely |
| **G3 · Improvement on held-out** | Split the corpus: **train** (proposer-visible) / **validation** (gate) / **owner-only rotating holdout**. `grounded_in` may cite train only. Candidate must beat a **null-hypothesis control cohort** (randomly mutated variants) at the 95th percentile — not merely beat the incumbent. State honestly that at n≈20 aggregate means have no power; report CIs, gate on the deterministic per-scenario rule |
| **G4 · Separation of powers** | Now **structurally enforced** by §2.2 rather than by inspecting a diff. Retains the owner-only field list, expanded per §1.9: `deterministic`, `side_effects`, `idempotency_key_fn`, `fallback_node_id`, `requires_deterministic_fallback`, and removal of any `requires_human_approval` |
| **G5 · Rate, drift, budget** | Rate limit on *accepted* changes; drift from an owner-blessed baseline with a **rebaseline rate limit** (closing the standing-pressure hole, §1.9); plus a compute budget and a cap on *surfaced* candidates (bounding owner load) |

**Canonical order** (cheap-first, and G4/G0 before anything expensive):
`G0 → G1 → G4 → G5 → G2 → G3`.

### 2.5 Sandboxing is now mandatory

The agent executes code it wrote during validation. Gate runs happen in an
isolated environment with no credentials worth stealing, no network egress
beyond an allowlist, and no write access outside a scratch dir. This was
unspecified in the original plan; with self-coding it is a precondition,
not a nicety.

### 2.6 Post-merge monitoring and auto-rollback

A merged code change carries regression risk a pre-merge review cannot
see — and, per §1.8, this design has **no** shadow execution or canary.
Post-merge outcome tracking with an automatic rollback trigger is therefore
required, not optional. It partially compensates for the missing
criteria 1/6 rather than pretending they were unnecessary.

### 2.7 Program kill criteria

Per Anthropic's *"add complexity only when it demonstrably improves
outcomes"*
([building effective agents](https://www.anthropic.com/engineering/building-effective-agents)):
if, after a defined trial period, agent-authored changes do not
demonstrably outperform an owner editing the code directly — **stop the
program.** Also halt on: any G4/Zone violation attempt, any accepted change
later found harmful, or owner review latency indicating rubber-stamping.

---

## Part 3 — What is honestly unresolved

1. **Owner review is the primary control and it does not scale.** A code
   diff is far harder to review than a YAML diff. The diff-size budget
   (§2.4 G0) is a partial answer; it is not a solution. If review degrades
   to rubber-stamping, the primary control is gone and nothing replaces it.
2. **The validation report is a prompt-injection channel into the human.**
   `rationale`/`grounded_in` are built from tool results and memory —
   attacker-influenceable — and rendered into the one artifact the entire
   safety case rests on.
3. **Reward hacking under self-coding is High, not Low.** DGM is the
   existence proof.
4. **No shadow/canary means no evidence from the real traffic
   distribution** before a change goes 100% live.

These are stated as exposures, not solved problems.

---

## Part 4 — Revised milestone order

Judge before judged, now including the control baseline:

| M | Milestone |
|---|---|
| **M0** | Reflection slice (unchanged — still the recommended start) |
| **M1** | CI trust boundary: base-ref gate execution + Zone path allowlist + sandbox. **Before any proposer exists.** |
| **M2** | Trace serializer + corpus, **split train/validation/holdout from day one** |
| **M3** | G0/G1/G4 (static safety, builds, zone enforcement) |
| **M4** | G2 outcome non-regression |
| **M5** | Eval suite + G3 **including the null-hypothesis control cohort** (no longer deferred) |
| **M6** | Archive + rollback, with source-digest pinning |
| **M7** | G5 rate/drift/budget |
| **M8** | Proposer (rule-based first) |
| **M9** | Review surface + proposal ledger + loop observability |
| **M10** | Post-merge monitoring + auto-rollback + kill switch + weekly digest |

**Approval policy:** per-change owner review is replaced by tiered
auto-merge — see `05-approval-policy.md` and ADR 0045. This makes **M10
load-bearing rather than optional**: with no human in the merge path,
post-merge monitoring is the primary safety net. M10 must ship before Tier-1
auto-merge is enabled; until then every candidate escalates (Tier 2).

**Recommended first build remains M0** — it is a genuine prerequisite,
carries no self-modification risk, and delivers standalone value.
**M1 must precede any proposer**, without exception.
