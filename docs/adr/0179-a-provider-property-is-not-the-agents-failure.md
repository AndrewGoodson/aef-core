# ADR 0179: A provider property is not the agent's failure

## Status

Accepted. Fix wave **J3** of the upgrade loop, closing the third seam hunt's
findings **R3**, **R4**, **R6** and **R7**. **Zero live model calls** — every
number below comes from a real `GraphExecutor` / `run_graph_module` run
against a real `CommandProvider` driving a real local subprocess, or from the
real adapter classes with a local runner. **No rubric dimension moves**; what
R6's closure means for dim 2's wording is stated at the end.

Four findings, one theme with two halves. Half one: **a fact about the
provider an owner installed was being recorded as something the agent did
wrong**, and it then propagated into the task metric, into failure memory and
into the agent's own prompt (R3), while the one place that fact was most
needed — a heterogeneous fallback chain — silently erased it (R4) and one of
the two harness adapters silently disagreed with the other about how to read
its own usage payload (R7). Half two: **the wire that puts what a repo learned
back in front of the model reached no repo the scaffold generates** (R6).

---

## R3 — every prompt-agent run on a system-channel-less provider scored 0, and M4 pasted the provider's warning into the persona

### The reproduction

`scratchpad/w/j3/repro_r3.py`: a synthetic adopter repo with one persona,
migrated by the **real** `run_migrate`, an `aef.yaml` naming
`model_provider.impl: command` with an argv template that has **no `{system}`
slot** — which is exactly ADR 0169's `codex` row, and exactly how ADR 0154
says every harness after Grok gets wired — and a stub CLI that answers the
question correctly. Three `run_graph_module` calls, one durable memory file:

```
generated: agents/migrated/answerer/graph.py
--- run 1 -----------------------------------------
  answer          : PARIS
  containment     : {'provider': 'command', 'isolation': ['user_turn_persona'],
                     'persona_role': 'user'}
  errors          : ['prompt_agent.persona_in_user_turn']
  task_completion : 0.0
--- run 2 -----------------------------------------            (identical)
--- run 3 -----------------------------------------            (identical)

failure records in memory: 3
  kind=failure run_id=25c2aed5-… failing_nodes=['prompt_agent']
  kind=failure run_id=ff9c7901-… failing_nodes=['prompt_agent']
  kind=failure run_id=78b6d9bd-… failing_nodes=['prompt_agent']
```

The agent answered `PARIS`. It scored `0.0` three times.

Three distinct runs is one more than ADR 0110's two-run threshold, so the
lesson is formed and `RuleBasedPromptProposer` — ADR 0157's M4 proposer,
which takes the highest-recurrence failure entry and appends it as a bullet —
had something to say:

```
reason: appended a bullet for 'failure:prompt_agent'
proposals: 1
--- proposed persona -------------------------------------
---
name: answerer
description: answers the objective.
---

# answerer

You answer the user's question in one word.

## Lessons (aef)

- <!-- aef sig=failure:prompt_agent runs=3 --> 1 error(s) recorded; 0/0 tool
  call(s) failed. errors[0]: {'node_id': 'prompt_agent', 'type':
  'prompt_agent.persona_in_user_turn', 'provider': 'command', 'isolation':
  ['user_turn_persona'], 'message': "provider 'comma…
```

### What is actually wrong with that

Three consequences, none of them intended by ADR 0169:

1. **A property of the CLI the owner installed became a bullet in the
   agent's prompt.** No sentence a persona can contain will give a binary a
   `--system-prompt` flag. The loop's one mechanism for changing behaviour was
   pointed at something behaviour cannot change.
2. **It occupies one of five bullet slots forever.** ADR 0116 evicts the
   stalest bullet by `runs_since_last_seen`; this lesson recurs on *every*
   run while the provider is unchanged, so its staleness never grows and it
   evicts real lessons rather than being evicted.
3. **The task metric is pinned at 0 for every prompt agent on a Codex
   adopter**, regardless of answer quality — `RuleBasedEvaluator` zeroes
   `task_completion` on any `state.errors` entry. That makes the loop's own
   evidence worthless on precisely the repos ADR 0152 was written for.

### The argument against ADR 0169's deliberate choice

ADR 0169 said this out loud rather than leaving it to be discovered:

> **But an error entry**, which means `RuleBasedEvaluator` scores that run 0.0
> and the failure reaches the loop's memory. That is deliberate […] under ADR
> 0152 the persona being the system message *is* the safety story, so a run
> where it was not should be visible to the thing that reads those signals.

The premise is right and the conclusion does not follow. "Should be visible"
is a claim about **surfacing**; `state.errors` is not a surface, it is a
**classification** — and everything downstream reads it as one. `failure_signals`
is documented as "the **single** 'what counts as a failure' convention";
`RuleBasedEvaluator` treats an entry as "this run did not complete";
`make_reflect_node` turns it into `kind="failure"`; the consolidator turns
recurrence into a lesson; the proposer turns a lesson into prompt text. ADR
0169 reached for `state.errors` to get one property — visibility — and
inherited four more it did not want.

And the fact does not have the shape of an error. `state.errors` means *this
run did something wrong*. The persona's channel is true **before the objective
is read** and **unchanged by the answer**: the node itself says so in the
comment above the line that reads it — *"the containment a run had is a
property of the provider it was given, not of whether the answer came back."*
That comment was already correct about the fact and the code then filed it
under the run's failures.

### The fix, and what "the smallest honest thing" turned out to be

The fact is recorded where the rest of that fact already lives — the
containment record the node writes on **every** run — under a `warning` key:

```json
"working_memory": {
  "prompt_agent__containment": {
    "provider": "command",
    "isolation": ["user_turn_persona"],
    "persona_role": "user",
    "warning": {
      "node_id": "prompt_agent",
      "type": "prompt_agent.persona_in_user_turn",
      "provider": "command",
      "isolation": ["user_turn_persona"],
      "message": "provider 'command' declares no system channel, so persona
       'answerer' was prepended to the USER turn. …"
    }
  }
}
```

**`state.warnings` was considered and rejected**, and the reason is
`AEFState`'s own docstring: *"Per-agent variation belongs in `working_memory`
/ `retrieved_context` payloads or in the five allowed per-agent surfaces —
never in new top-level fields on this model."* A new field on the one shape
every agent shares would also need a `StateDelta` field, a schema-version
migration and a pass over every checkpoint on disk, to hold something one node
writes. `StateDelta` already offers `working_memory`; the containment dict was
already in it; one key is the whole change.

The same three runs, after:

```
--- run 1 -----------------------------------------
  answer          : PARIS
  containment     : {'provider': 'command', 'isolation': ['user_turn_persona'],
                     'persona_role': 'user', 'warning': {'node_id':
                     'prompt_agent', 'type':
                     'prompt_agent.persona_in_user_turn', …}}
  errors          : []
  task_completion : 1.0
--- runs 2 and 3 ---------------------------------- (identical)

failure records in memory: 0
reason: no admissible failure record for this graph
proposals: 0
```

`containment_warnings(state) -> list[tuple[str, dict]]` is **the** reader, so
a doctor command or a cycle summary surfaces the fact without re-deriving
where it is kept. Visibility — 0169's actual goal — is now served by a reader
built for it rather than by a classification borrowed for it.

**Reflect's failure classification is unchanged, deliberately.** The honest
fix is not to record the fact as an error in the first place; adding a filter
inside `make_reflect_node` for `prompt_agent.*` types would create a *second*
answer to "what counts as a failure", which `failure_signals`' own docstring
says is "a bug in the making".

### The second line of defence, and it was verified against a planted fault

`RuleBasedPromptProposer` now drops any record whose text names a
`prompt_agent.*` type, counts the drops and says so:

```
reason: 3 record(s) dropped as a provider fact rather than a lesson (a
`prompt_agent.*` containment note describes the CLI the owner installed, not
what this agent did, and a persona cannot act on it); no admissible failure
record for this graph
```

Two things about this filter are worth stating rather than implying.

**It matches on the record's TEXT, not on the signature, and that is
measured.** The signature of the reproduced case is `failure:prompt_agent` —
a **node id**. Refusing that prefix would discard every genuine lesson the
prompt-agent node ever produces, on every repo, which is a far worse defect
than the one being fixed. The error type is the only thing in the record that
names the provider property, and the record carries it inside
`verbal_feedback` because that is the string `RuleBasedCritic` builds. A text
match is the honest description of what this filter can see. Every string in
`content` is scanned, including inside lists, because that dict is
`dict[str, Any]` and a filter that reads one field is one refactor away from
reading none of the right ones.

**Its value is that it holds when the first line does not.** With M1 applied
alone — the error put back into `state.errors` — the score returns to `0.0`
and three failure records reappear, and the proposer *still* refuses the
bullet. It takes M1 **and** M2 together to get the sentence back into the
persona. That is what defence in depth is supposed to look like, and it is the
reason a second line was worth the code.

---

## R4 — `FallbackProvider.isolation` intersected away the one marker that must not be intersected

### The reproduction

`scratchpad/w/j3/repro_r4.py`, against the **real** `ClaudeCodeProvider` and
`CodexProvider` — no calls, `isolation` is a property:

```
claude   role=system  isolation=['no_mcp', 'no_project_context', 'no_tools',
                                 'single_turn', 'system_role']
codex    role=user    isolation=['read_only_fs', 'user_turn_persona']
fallback role=unknown isolation=[]
```

and through the node, with the primary raising `ModelProviderError` and the
`codex`-shaped backup answering:

```
through the node, backup answering:
  containment: {'provider': 'fallback', 'isolation': [], 'persona_role': 'unknown'}
  errors     : NONE
```

The persona **did** go out in the user turn. Nothing said so.

### Why the intersection was right and still wrong

Intersection is correct for a **claim**: "this call reaches no tool" holds for
a chain only if it holds for every member, because the caller does not choose
who answers. `system_role` / `user_turn_persona` are not claims of that shape.
They are **mutually exclusive per provider**, so intersecting a heterogeneous
chain erases *both*, and `persona_role()`'s third state — `unknown`, which
exists to mean "the provider declared nothing" — starts also meaning "two
providers declared opposite things". Those are different facts and the node
treats one of them as a reason to stay silent.

`ISOLATION_PROPERTIES` had the two halves in one set with a comment between
them. They are now two sets: `CHANNEL_PROPERTIES` names the pair, and the
composition rule differs by half.

### The rule

- **claims**: intersection, unchanged, for the unchanged reason;
- **channel**: any member declaring `user_turn_persona` → the chain declares
  it; otherwise `system_role` only when **every** member declares it; a member
  saying nothing about its channel leaves the chain with no channel claim.

The last clause is ADR 0169's own rule pointed the other way: manufacturing a
claim out of an absence is how one sentence about one adapter survived five
providers, and manufacturing a *safety* claim out of an absence would be worse.

After:

```
fallback role=user    isolation=['user_turn_persona']
  containment: {'provider': 'fallback', 'isolation': ['user_turn_persona'],
                'persona_role': 'user', 'warning': {…}}
```

### What this rule is not

It is **conservative, not exact**. The finding suggests resolving the channel
from the member that actually answered. `isolation` is a static property read
before any call, and the only ways to make it per-call are to mutate the
provider (shared across threads, order-dependent) or to add a channel field to
`CompletionResult` that every adapter must then populate. So on a chain whose
primary answers 999 times out of 1000, this reports a containment note the
persona did not incur.

**That trade is only affordable because of R3.** While the marker produced an
`errors` entry, a conservative false positive cost a chain-configured adopter
its entire task metric, and the incentive was to be silent when unsure. Now
the note costs attention and nothing else, while silence costs evidence — so
the asymmetry that made "exact-or-silent" tempting is gone. The two findings
are one fix in two files.

One consequence in the wording: the node's message says the provider
"**declares** no system channel" rather than "has none", because on a chain
the second sentence would be false.

---

## R7 — `usage_match` was wired into one of two adapters that share one function

### The reproduction

`scratchpad/w/j3/repro_r7.py`, identical payloads through both real adapters
with a local runner:

```
answering_model WITH usage   : ('big-answerer', 'usage_match')
answering_model WITHOUT usage: ('big-answerer', 'heuristic')

ClaudeCodeProvider -> model=big-answerer   attribution=usage_match
GrokProvider       -> model=big-answerer   attribution=heuristic
claude  call site: ['answered_by, attribution = answering_model(model_usage, requested, usage)']
grok    call site: ['answered_by, attribution = answering_model(model_usage, requested)']
```

ADR 0169's addendum added rule 4 and wired it into `ClaudeCodeProvider` only.
`heuristic` is the rule that ADR 0169's D1 **measured wrong 1 time in 36**;
`usage_match` is deterministic. Two adapters, one function, two answers.

### The test named for the property could not see it

`test_grok_uses_the_same_rule_so_the_two_adapters_cannot_drift` passes
`model="grok-4.6"`, so **rule 2 answers before rule 4 is ever consulted** —
`grok-4.6` extends to `grok-4.6-build` and the function returns `alias`. The
test is green under both the fixed and the broken code. It is kept (rule 2 is
worth pinning) and joined by
`test_grok_reaches_attribution_rule_4_the_same_way_claude_does`, which sends
`model=""` and a two-key map whose **first key writes more output than the
answering model** — the ADR 0169 D1 shape — so the heuristic picks the helper
and rule 4 picks correctly, and the two adapters are asserted equal on the
identical payload.

### The caveat, stated

ADR 0154's observed Grok payload has a **single-key** `modelUsage`, which rule
3 answers as `sole` before rule 4 is reached. The two-key trigger is
**constructed**. What this fix and its test buy is that the two adapters
cannot diverge; it is not a claim that Grok has been seen billing a helper
model.

---

## R6 — the retrieval wire reached no generated graph

### The reproduction

`scratchpad/w/j3/repro_r6.py`, real `run_migrate` then three real runs:

```
generated graph nodes: ['consolidate', 'prompt_agent', 'reflect']
mentions make_retrieve_node: False
mentions render_retrieved_context: False
run 1: retrieved_context=[]
run 2: retrieved_context=[]
run 3: retrieved_context=[]
record retrieved_signatures: []
record retrieved_signatures: []
record retrieved_signatures: []
entry sig=failure:prompt_agent occurrences=3 helpful=0 harmful=0
```

A lesson formed — three occurrences, one entry — and no run ever saw it. The
tally ADR 0118 records is a constant, so ADR 0157's rationale prints
`helpful 0 / harmful 0` on every proposal an adopter will ever produce.

`render_retrieved_context` (ADR 0155) had exactly one caller,
`agents/summary/graph.py::draft_node`, which is **this repo's own fixture** and
ships in no adopted repo. `make_retrieve_node` (ADR 0118) had the same one
production caller. ADR 0155 closed "a caller that writes state nobody reads"
for the fixture and left it open for every repo `aef migrate` generates — the
same shape one level out, which is worth naming because it is the third time
in this program that a wire was closed in the demo and not on the path.

### The fix

Two halves, because either alone still writes state nobody reads.

**The template gains a retrieve node**, so `aef migrate` now generates

```
retrieve -> prompt_agent -> reflect -> consolidate -> END
```

with `entry_node="retrieve"`. Before the work, not after: a lesson retrieved
after the answer is a record of learning rather than an instance of it.

**`PromptAgentNode` renders the lessons into the USER turn**, after the
objective:

```python
lessons = render_retrieved_context(state)
user_turn = f"{state.objective}\n\n{lessons}" if lessons else state.objective
```

### Why the user turn and not the system prompt

Three reasons, in the order they bind:

1. **The persona is never modified at runtime.** ADR 0152's containment story
   is that the file in Zone A *is* the system message. Splicing runtime text
   into it would make the system prompt something this runtime composed
   rather than something an owner wrote, the gates measure drift on, and G5
   bounds.
2. **A lesson is derived from model output.** Putting it in the system channel
   grants text the runtime produced the authority of the operator's
   instructions — the elevation `PolicyEngine`'s deny-by-default exists to
   refuse (constraint #6). Lessons are evidence about earlier runs; evidence
   is data, and data belongs in the turn data arrives in.
3. **On half the providers there is no difference anyway.** Under
   `user_turn_persona` the system text is concatenated into the user turn, so
   a "system-prompt" placement would be a distinction only some backends could
   keep.

**Byte-identical when nothing was retrieved**, pinned by
`test_the_request_is_byte_identical_when_nothing_was_retrieved`: no header, no
trailing newline, the objective and nothing else. Every cassette recorded
before this change stays on its hit path (ADR 0123).

### End to end, after

`scratchpad/w/j3/verify_r6.py` — real `run_migrate`, two planted records under
one signature in two distinct runs (ADR 0110's threshold), one real run
through a CLI that echoes the prompt it was handed:

```
template mentions make_retrieve_node: True
entry_node: ['entry_node="retrieve",']

retrieved chunks: 3
--- the USER turn the provider actually received -------------
What is the capital of France? Answer in one word.

Lessons from this agent's earlier runs (most relevant first):
- [failure:prompt_agent] ALWAYS-NAME-THE-COUNTRY-TOO
- [failure] ALWAYS-NAME-THE-COUNTRY-TOO
- [failure] ALWAYS-NAME-THE-COUNTRY-TOO
--------------------------------------------------------------
lesson text in the user turn: True
reflection record retrieved_signatures: ['failure:prompt_agent']
```

`retrieved_signatures` is non-empty on an adopter's reflection record for the
first time, which is what the helpful/harmful tally needs to stop being 0/0.

---

## Green bar and mutations

`pytest -q` **2520 passed, 6 skipped** (2526 collected, from 2516 at the
branch point `db2987a`: **+10, none removed**). `mypy aef examples` clean on
134 source files. `ruff check .` clean. `ruff format --check aef tests
examples` clean. `tests/test_vendor_isolation.py`, `tests/test_prompt_surface.py`
and S1's golden (`tests/agents/test_summary_prompt.py`) green.

Two tests were **deliberately rewritten** rather than worked around, because a
test that pins wrong behaviour defends the defect through every refactor:

- `test_a_persona_sent_in_the_user_turn_is_warned_about_and_not_refused` —
  asserted the warning was `delta.errors[0]`, which pinned the behaviour that
  scored a correct answer 0.0. Same warning, same words, asserted where it now
  lives, plus `errors == []`.
- `test_the_generated_graph_builds_and_is_wired_to_reflect` — asserted
  `entry_node == "prompt_agent"` and a three-node graph.

Seven mutations, six detected and the control correctly not, each restored
from a `shasum -a 256`-verified byte backup — never `git checkout --`. The
harness purges `__pycache__` and runs `python -B`, because ADR 0169's M7 was
reported as a hole in the suite by a stale `.pyc`.

| | mutation | result |
|---|---|---|
| M1 | the containment fact goes back into `state.errors` | DETECTED |
| M2 | the proposer stops refusing provider facts | DETECTED |
| M3 | a fallback chain intersects the channel marker again | DETECTED |
| M4 | Grok stops passing `usage` to `answering_model` | DETECTED |
| M5 | the generated template loses its retrieve node | DETECTED |
| M6 | the node stops rendering retrieved lessons into the user turn | DETECTED |
| M7 | *control:* a no-op comment reflow in the same function | NOT DETECTED, correctly |

M1 was additionally run **as the finding words it** — the mutation applied,
then the original three-run reproduction re-executed rather than the test
suite:

```
  task_completion : 0.0   (x3)
failure records in memory: 3
reason: 3 record(s) dropped as a provider fact rather than a lesson …
proposals: 0
restored, sha256 verified: 4e67262a33c295d4
```

and with M1 **and** M2 applied together, the bullet comes back verbatim:

```
  task_completion : 0.0
failure records in memory: 3
reason: appended a bullet for 'failure:prompt_agent'
proposals: 1
- <!-- aef sig=failure:prompt_agent runs=3 --> 1 error(s) recorded; … 'type':
  'prompt_agent.persona_in_user_turn', … 'isolation': ['user_turn_persona'] …
restored prompt_agent.py 4e67262a33c295d4
restored prompt_proposer.py 9d8927b45b951861
```

---

## Consequences

- **A `codex`- or slotless-`command`-backed prompt agent no longer scores 0.0
  on `RuleBasedEvaluator` and no longer appears in failure memory.** This
  directly reverses a consequence ADR 0169 listed as intended, with the
  measurement above as the reason.
- **A heterogeneous `fallback:` chain now declares `user_turn_persona`**, so
  such a chain always records a containment note even on runs the primary
  answered. Conservative by design; see R4's "what this rule is not".
- **`aef migrate` generates a four-node graph.** Anything asserting the
  generated entry node or node set — an adopter's own test, a gate baseline —
  sees `retrieve` first. Running it needs `Services.retriever`, which
  `agent_services` defaults (ADR 0118); a hand-built bare
  `Services(model_provider=...)` does not, and the generated docstring says so
  alongside the four services it already named.
- **`GrokProvider.model_attribution` can now report `usage_match`.** No
  observed payload reaches that path today.
- **Open and named:** surfacing the containment warning in `aef loop doctor`
  and the cycle summary. `containment_warnings()` is the reader, written and
  tested; `aef/cli/loop.py` and `aef/cli/preflight.py` belong to another
  worker in this wave and were not touched. Until that lands, the fact lives
  in the trace and in `working_memory` and nothing prints it — which is
  strictly more visible than it would be if this ADR had simply deleted the
  entry, and strictly less than it should be.

## What R6's closure means for the rubric — and what it does not

**No dimension moves here, and nothing is claimed about task quality.** No arm
was scored; there were zero live model calls.

The dim-2 row (17/20) carries J0's finding as its open clause: *"`make_retrieve_node`
writes `retrieved_context` and **no prompt reads it** — `draft_node` builds
from `working_memory` alone."* ADR 0155 closed the second half of that
sentence for `agents/summary/graph.py` and appended an erratum saying so. What
was still true after 0155, and is what R6 measured, is the **first** half on
every repo the scaffold generates: the retrieve node did not exist there at
all, so there was no `retrieved_context` for a prompt to read. That clause is
now false on both the fixture and the generated path — a lesson consolidated
from an adopter's own runs reaches that adopter's next prompt, demonstrated
end to end above.

**That is a wire, not a score.** The clause dim 2 would need next is the one
ADR 0155's four-arm measurement already failed to establish and stated
plainly: retrieval in context has not been shown to improve a task metric on
any corpus in this repo. R6 removes the reason that measurement was impossible
to run on an adopter (there was no arm (b) or (c) to run) and supplies none of
the evidence. The row stays 17/20 and its "remaining" text is now accurate
about a different thing: not "no prompt reads it" but "no measurement shows
reading it helps".

## Erratum — the "Open and named" item is CLOSED (ADR 0182)

**K3-4 of the K wave gave `containment_warnings()` its callers.** `aef loop
doctor` prints

```
  [!!] persona channel  prompt_agent: persona sent in the USER turn by provider
       'codex' (isolation: read_only_fs, user_turn_persona) — see ADR 0179
```

**below** `Preflight.render()` and outside the six obligations — a property of a
CLI the owner already installed has no `fix:` that is an edit in this repo, and
adding it to the list would make `doctor` exit 1 forever on a correctly
configured Codex adopter, which is this ADR's own R3 finding one surface over.
`cycle` and `gate` print the same sentence beside the verdict, one line per
**distinct provider**, and both are silent when the persona was the system
message.

Two things this ADR left implicit, settled by running them:

- **the memory store is not a source, and that is now asserted.** R3's whole
  point is that the fact never becomes a `MemoryRecord`, so a reader looking
  in `--memory` would find nothing on every repo. The sources are the corpus
  scenarios and the most recent recorded run under `--runs`, which is a new
  flag on `doctor`.
- the closing sentence — the fact is "strictly more visible than it would be if
  this ADR had simply deleted the entry, and strictly less than it should be" —
  is now false in its second half.

**One defect found while closing it, reported in ADR 0182 and not fixed there:**
through the recording path an adopter actually uses (`aef loop bootstrap
--config`), the containment record says `provider: 'cassette'` rather than
`'codex'` — the recording wrapper's `.name` reaches the dict while `isolation`
passes through correctly. So the surfaced line names a wrapper instead of the
CLI the owner installed.

## Confidence

**High** on all four reproductions: each was run before anything changed, the
output is pasted above verbatim, and each was re-run after. High on R3's fix —
the behaviour change is a one-key move whose consequence is visible in the
task metric of a real run, and both lines of defence were mutation-checked
independently and together. High on R7, which is a one-argument omission
demonstrated against both real adapters.

**Medium** on R4's rule. The reproduction and the erasure are certain; the
*choice* of conservative-over-exact is a judgement, and it produces a note on
runs whose persona travelled in the system channel. The argument for it rests
on R3 having made that note cheap, so if a future change makes containment
notes costly again this rule should be revisited before that change lands, not
after.

**Medium** on R6's usefulness, as distinct from its correctness. That the
lesson reaches the user turn is measured. That it *helps* is not, on this
corpus or any other — see the rubric note above. The placement argument (user
turn, not system prompt) is a safety argument and is not measured either; it
is the same argument constraint #6 already makes, applied one level down.

**Low**, and unchanged, on anything about a harness this repo has not run.
`impl: command` remains the owner's assertion recorded as one.
