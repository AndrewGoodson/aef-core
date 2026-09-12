# ADR 0205: Explicit capabilities, recorded context, native prompt definitions

Date: 2026-09-08. Status: implemented on the review branch; live prompt quality
unverified. Scope and evidence: [review](../model-checks/2026-09-08-codex-review.md).

## Problem

ADR 0204's first real-repository lesson reduced the recorded comparison from
0.6667 to 0.4000; a live placebo scored 0.8667. This is evidence against
readiness. It is not a clean estimate of the effect against the incumbent:
the incumbent was replayed, the other arms live, and resampling the incumbent
alone changed its score by +0.2. No new live result is claimed here.

Three implementation defects undermine even a careful evaluation:

1. A tool-using persona is invoked by a provider that declares `no_tools`,
   without telling the persona its runtime has changed (F-Q1-1).
2. A durable-memory run is replayed with empty memory. Later runs are rejected
   as nondeterministic because a service input is missing (F-N7-1).
3. Migration searches only Claude Markdown. Codex TOML and Grok Markdown
   definitions can be present without producing executable prompt graphs.

## Decision

### State the actual capability boundary

`PromptAgentNode` appends a runtime message when the provider declares
`no_tools`: tools are unavailable, tool results must not be invented, and
missing evidence must be named. Retrieved lessons are fallible evidence,
not permissions. The original persona stays intact. An unknown declaration
does not acquire a claim of containment.

We choose this over granting tools or rejecting every tool-oriented persona.
It supports evidence-only tasks while preserving existing containment. A
persona can describe a task that requires tools; that task cannot be completed
by a tool-free invocation, and the instruction must say so. This message is
not a sandbox, and tests of its presence do not prove model compliance.
Native model/tool/MCP/sandbox settings are never translated into AEF grants.

The request changes, so an old cassette may miss. Do not rewrite captures or
manufacture a new historical score to conceal that difference.

### Capture the service inputs needed for replay

New CLI recordings using `FileMemoryStore` capture the agent's ordered
pre-run records before consolidation and execution. `RecordedRun` and
`Scenario` carry that snapshot and the provider's observed declarations.
Harvest, the ordinary scenario runner and the isolated worker restore the
snapshot and rebuild the built-in rule-based knowledge projection.

`SnapshotMemoryStore` preserves append order and query/get semantics without
writing to the live store. Each recorded scenario restores its own snapshot,
including when scenario order is reversed. `RecordedIsolation` carries
metadata only and cannot answer a completion. A missing live provider remains
a scored cassette miss, never a dead-call exemption or an implicit live call.

`initial_memory=None` means a legacy recording without captured memory. It
does not authorize reading today's memory file or guessing historical state.
This does not serialize arbitrary external stores or custom knowledge
services. Snapshot tenant IDs are checked. Redaction still scans the content;
canonical UUID4 run metadata and repeated structured provenance are excluded
from false-positive scanning, but matching UUIDs inside tenant text remain
detectable. Provenance metadata is not a cryptographic attestation.

### Support verified native definitions

Default migration discovers `.claude/agents/**/*.md`,
`.codex/agents/**/*.toml` and `.grok/agents/**/*.md`. Codex TOML must have
nonempty `name`, `description` and `developer_instructions`. Other settings
are reported without application. Names are disambiguated while reserving
existing suffixes; symlinked source paths are refused.

The prompt proposer can add lessons to TOML `developer_instructions`,
preserving other fields and syntax. Supporting a format does not put its
directory in Zone A: every persona's actual zone is reported, and selecting
one remains an explicit adopting-repository scope choice.

Adoption distributes the same evidence-learning protocol through its managed
instruction blocks and integration guide. Existing owner text outside those
blocks and the native definitions are preserved. Root `AGENTS.md` and
`CLAUDE.md` are reconciled and have a byte-equality regression.

### Make learning evidence explicit

The [protocol](../autonomy/evidence-learning.md) requires task scope, pinned
inputs, an evidence card with a counterexample, a bounded proposed change,
reproduce-first verification and separate held-out evaluation. Repetition is
not truth. A lesson must not override policy or introduce evaluator answers.

This applies ideas from reflective prompt search, structured context updates
and durable graph execution. It does not implement GEPA, ACE, a new optimizer,
automatic lesson deletion, graph evolution or a tool-capable runtime. Paired
live incumbent/candidate trials remain an owner-authorized cost decision.

## Supporting corrections

Generated run commands allocate fresh work directories; an agentless owner is
asked for an objective, not nonexistent legacy entrypoints. `doctor --config`
reads committed halt configuration without executing it. Archive guidance
names `--graph-id`; it does not reconcile mismatched archive defaults.
An unmeasured harvest count renders `unknown`, not zero. Both scenario runners
expose recorded exception types even after a graph fallback, without copying
sensitive error bodies. The broader G2 headline and live/replay comparison
issues remain open; the review records partial fixes separately.

## Validation and consequences

The five-run persistent-memory reproduction now harvests and replays all five
runs without changing its source store. Native-format fixtures compile,
survive repeated adoption, preserve owner bytes and retain scope boundaries.
Production mutations restore the faults and the tests detect them; source
hashes are checked after restoration. The review contains final suite results
and the mutation manifest.

No new dependency, provider permission, evolution enablement, Tier-1 merge,
held-out data write, deployment or mutation of another repository is part of
this decision. Mechanism correctness has improved; useful self-learning on
real repositories still needs evidence.
