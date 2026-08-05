# ADR 0101: Triage of the named-but-unbuilt

## Status
Accepted. Milestone 3. **Deletes four interfaces. Implements one.**

## The test applied

Milestone 3 asked one question of each unbuilt interface: does the **loop**
need it, does an **adopter** need it, or is it **design ambition**? And it
gave permission to conclude "delete this" — *a stub unimplemented across five
phases is a promise, and an unkept promise in a typed signature is worse than
an honest absence.*

Facts gathered first, by grep rather than by memory. Every reference to all
five, outside its own defining module, was one of exactly two things: an unread
slot on `Services`, or `tests/test_phase2_5_stubs.py` — a test that asserts
calling the stub raises `NotImplementedError`. **That is what a promise looks
like when it is tested.**

| Interface | Loop? | Adopter? | Verdict |
|---|---|---|---|
| `GraphStore` | no | cannot | **delete** |
| `PlanValidator` | no | already served | **delete** |
| `Planner` | no | no | **delete** |
| `TokenOptimizer` | no | not honestly | **delete** |
| `Retriever` | yes, via a budget nothing enforced | yes | **implement** |

## The four deletions

**`GraphStore`.** ADR 0100 already wrote the argument one milestone ago: a
knowledge graph needs a query interface, a result shape the context engine can
budget, and a provenance story for retrieved facts, and the node signature
carries none of the three. The config now *refuses* a `knowledge_graph` block
outright — so `Services.graph_store` was a slot no code filled and no config
could configure. Keeping the ABC while refusing to configure it is
incoherent; the deletion makes the two agree.

**`PlanValidator`.** `validate(plan, state) -> bool`, documented as "e.g. a
Financial Agent's Sharpe/PF/MaxDD gates, a Security Agent's blast-radius
gate (report §16)". `RuleBasedEvaluator.domain_gates` is documented as
"exactly the pluggable per-agent surface report §16 describes (e.g. a
Financial Agent's Sharpe/PF/MaxDD gates, an Azure Security Agent's
blast-radius gate)". **Two interfaces, one report section, the same worked
examples, for one job.** Milestone 2 built and wired one of them, reachable
from `aef.yaml` and applied to real runs. The other is now redundant, and a
redundant interface is worse than none because an adopter must guess which is
real.

**`Planner`.** The loop never invokes it. An adopter's agent already plans in
its own nodes, and the scaffold's job is to make planning *replayable and
gated*, not to own the planning. Design ambition, and deleting it changes
nothing anybody could observe.

**`TokenOptimizer`.** `compress(text, budget)` cannot be built honestly
without a model — and a "compressor" that truncates is a lossy edit wearing
the word compression. Report §13's own rule is that nothing may optimise for
fewer tokens as an end in itself. The half of it that *can* be done honestly
is budget enforcement by pruning whole units rather than damaging them, and
that half now lives in the retriever.

Deleting these breaks nothing that ever worked: all four are abstract with
`NotImplementedError` bodies, so no implementation of them can exist that
anything calls. The contracts are recorded here for whenever one returns.

## The one implementation

`MemoryRetriever` survived triage, and **not because retrieval is
interesting**. It survived because of what it makes true:
`AEFState.context_budget_tokens` has shipped since Phase 0 with a default of
8000, is carried faithfully through every `StateDelta`, and **no code has ever
read it to bound anything.** A token budget nobody enforces is the same defect
as an injection point nobody calls, and this is the first thing in the repo
that enforces it.

Retrieve → rank → prune, bounded by the budget. Deterministic — lexical
overlap, no model, no embedding — because `ReplayEngine` re-executes
deterministic nodes and asserts their output matches (constraint #1), so a
retriever a node may call must answer identically twice. The ranking is
Jaccard overlap, said plainly rather than dressed up: it has a real failure
mode, which is that a query sharing no vocabulary with a relevant record does
not find it. An embedding-backed retriever belongs behind this same interface.

Reachable from `aef.yaml` via a `context:` block, whose `impl` is **refused**
unless it names something that exists — the same discipline as ADR 0100.
`context.token_budget` is an owner-set **ceiling** a node cannot exceed,
rather than a default it could ignore; making it a default would have left it
a config field nothing reads, which is the defect this milestone removes.

3c's bar was "exercised by a test that runs it, not one that asserts it
exists". The test drives `run_graph_module` end to end: a real `aef.yaml`, a
real file-backed memory store with real records, and a real node calling
`services.retriever` whose output lands in `state.retrieved_context`. Its
control asserts the same node gets **no** retriever without the config block —
without which the test would prove nothing about the config reaching anything.

## What the adversarial round found

**`agent_id` defaulted to `None`, which meant every agent's memory.** A
retriever built without thinking about scope handed one agent another's
recorded failures. Reproduced. `agent_id` is now a required argument; `None`
still means "all agents" and must now be *chosen*. Deny-by-default is the
discipline everywhere else in this repo (constraint #6), and a convenience
default that widens scope was the one place it was not.

**A comment of mine claimed `candidates_per_kind` "bounds the work, not the
answer". It bounds both.** The store returns most-recent-first, so a relevant
record past the cap is never scored and can never be returned. That is a real
ceiling on recall. This is the same shape of error as ADR 0088, 0093 and 0096:
a true statement about one property offered as an answer about a different
one. Now stated, and pinned by a test that fails if the record becomes
reachable at the default cap or unreachable at a raised one.

Checked and sound: cross-kind tie ordering is stable; the candidate cap does
bound the read; content JSON cannot serialise does not break retrieval; and
non-ASCII text inflates under `json.dumps` escaping, which pushes the estimate
*conservative* rather than over-budget.

## Consequences

`tests/test_phase2_5_stubs.py` covered thirteen interfaces and now covers
nine. `Retriever` remains listed there as an ABC and is no longer only that.
The list is now an honest inventory of what has not yet earned an
implementation, rather than a list of promises with a test each.

## Confidence
High on the deletions — the evidence is mechanical, and nothing that ever
worked can break.

Moderate on the retriever. It is real, enforced and exercised, and its ranking
is the weakest part by design: lexical overlap will disappoint anyone
expecting semantic search, and the recall ceiling from `candidates_per_kind`
is a genuine limitation rather than a tuning knob. Both are stated in the code
where someone will read them.
