# ADR 0140: The routed form dropped the request, not just the retries

## Status

Accepted. Fix wave C of the ready loop; record in `IMPROVE_LOG.md`.
**No rubric score moves** — this is a correctness-and-safety fix to ADR 0137's
routed node form, shipped hours earlier.

Supersedes nothing. **Corrects ADR 0137**, whose falsification clause is
amended by erratum in that file.

## Context

ADR 0137 taught `aef migrate` to generate a **routed** node — one that calls
`services.require_model_provider().complete(...)` instead of the adopter's own
function — whenever the function is "nothing but the call". Its falsification
clause enumerated what routing must not silently drop: retries, loops,
`try`/`except`, streams, a guessed model id, a transitively-reached outer
wrapper. Every one of those is **control flow**.

It never asked whether the **request** survives translation.
`CompletionRequest` has five fields — `messages`, `model`, `max_tokens`,
`temperature`, `metadata` — and that is the whole contract. A call site passing
anything else has nowhere to land, and the generated docstring told the adopter
the opposite: *"there is nothing here for routing to lose"*, and *"whatever
your function did around it is yours to re-express"* — naming a place that does
not exist.

A seam hunt reproduced four defects in that form. All four are in the same
direction: **the generator routed calls it should have refused.**

## Evidence — reproduced first, by running, before anything changed

All commands from the worktree; `PYTHONPATH`/venv prefix elided.

### R1 — routing silently drops every request field `CompletionRequest` cannot express

`.scratch/seam2/s9/agent.py` — a claims adjuster with a hard payout ceiling in
its system prompt, a tool grant, stop sequences and `temperature=0.0`:

```python
def ask(prompt: str) -> str:
    client = anthropic.Anthropic()
    r = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system="You are a claims adjuster. NEVER approve a payout above $5,000.",
        temperature=0.0,
        tools=[{"name": "lookup_policy"}],
        stop_sequences=["</done>"],
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text
```

```
$ aef migrate --dir .scratch/seam2/s9
  ROUTED   agent.ask:4  (anthropic.Anthropic)
            -> services.require_model_provider().complete(model='claude-sonnet-4-6')
            routed because its body builds the client and makes exactly one
            completion call, with no loop, no try/except and no stream —
            there is nothing here for routing to lose
```

and the node it wrote:

```python
    result = services.require_model_provider().complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content=state.objective),),
            model="claude-sonnet-4-6",
            max_tokens=8192,
        )
    )
```

The payout ceiling, the tool grant, the stop sequence and the sampling
temperature are all gone, and the node's own docstring says nothing was lost.
`tools=` and `stop_sequences=` have no representation in `CompletionRequest` at
all, so "yours to re-express" names a place that does not exist.
`_routing_decision` compared the call's keywords against nothing whatsoever,
and no test in `tests/cli/test_migrate.py` passed any keyword beyond `model`,
`max_tokens` and `stream`.

**One correction to the seam hunt's framing, found by checking it.** A system
prompt *is* representable: `ProviderMessage.role` includes `"system"`, and both
`AnthropicProvider` and the harness providers fold system-role messages into
the vendor's system parameter. What is missing is a `system` **field** on
`CompletionRequest` and any way for a generator to decide how a literal system
prompt pairs with the user turn this node substitutes (`state.objective`, not
the call site's `messages`). So the refusal is right and its reason is
narrower than "nowhere to put it" — it is stated that way in the code, and
carrying a lone literal `system=` as a synthesised system-role message is
recorded below as a possible follow-up rather than done here.

### R2 — bare decorators, `**kwargs`, and a configured client are routed

`.scratch/seam2/s1/` — seven counter-shapes, scanned:

```
ROUTED    src.a_retry_decorated.ask_retry_bare      # @retry, bare
UNROUTED  src.b_retry_called.ask_retry_called       # @retry(...), by accident
UNROUTED  src.c_global_client.ask_global
UNROUTED  src.d_const_model.ask_const_model
ROUTED    src.e_kwargs.ask_kwargs                   # **kwargs into the SDK call
ROUTED    src.g_custom_client.ask_custom            # base_url= gateway
SKIPPED   src.f_async.ask_async
```

Three routes that should not be:

- **`@retry` bare** is an `ast.Name`, not an `ast.Call`, so it leaves no `Call`
  node in `decorator_list` for the "its body also calls `retry()`" rule to trip
  over. The *called* form `@retry(stop=...)` was refused only by that accident,
  and the reason it printed was about the body. Retries were dropped for the
  bare form.
- **`**kwargs`** is an `ast.keyword` with `arg=None` and was filtered out
  before any keyword was read, so the call looked thin. A caller passing
  `stream=True` at runtime then defeats the stream check without touching the
  code migrate read.
- **`anthropic.Anthropic(base_url="https://llm-gateway.corp/v1", timeout=120.0,
  max_retries=8)`** — the corporate-gateway shape — routed, so the generated
  node quietly reaches a different endpoint, on a different credential, billed
  to a different account, with the SDK's own retry policy gone.
  `Services.model_provider` resolves its own endpoint and key; none of that is
  expressible through it.

ADR 0137's Confidence section *predicted* the decorator and `base_url` cases in
prose, and shipped the routed form anyway. A predicted defect that ships is a
defect.

### R10 — `migrate --force` silently discards adopter edits

`aef loop doctor`'s "model calls visible" obligation prints
`aef migrate --dir . --force` as its fix. Hand-edit the generated node, then run
that line:

```
$ ... edit aef_migrated.py, adding "# HAND EDIT: adopter re-expressed the system prompt here"
$ aef migrate --dir . --force
wrote .../aef_migrated.py
EXIT=0
$ grep -c "HAND EDIT" aef_migrated.py
0
$ ls -a          # no backup anywhere
aef_migrated.py  probe.py  src
```

No backup, no diff, no warning, exit 0 — three lines below a comment in the
same function reading *"A generated file the operator has since edited is the
expensive thing to lose."*

### R11 — every generated node declares `side_effects` PURE

`render()` emitted `Node(...)` with no `side_effects`, so every node took the
`SideEffect.PURE` default:

```
side_effects declared in generated file: False
node.side_effects        : pure
node.idempotency_key_fn  : None
add_bounded_retry ACCEPTED a live routed model call as PURE: add_bounded_retry
['    for _attempt in range(RETRY_ATTEMPTS):']
```

`add_bounded_retry`'s guard reads the declaration from source and its own
comment says it *"requires the declaration rather than assuming it"* — but the
requirement is `if effects is not None and ...`, so an **absent** declaration
skips it entirely. The generator never wrote one. The self-improving loop could
therefore wrap a live, billed, routed model call in a 3-attempt retry without
anyone answering the question the guard exists to ask.

## Decision

### 1. Route only when every keyword at the SDK call is expressible

The allowed set is derived from the request type itself:

```python
_REQUEST_FIELDS = frozenset(f.name for f in fields(CompletionRequest)) | {"messages"}
_CARRIED_FIELDS = tuple(f.name for f in fields(CompletionRequest) if f.name != "messages")
```

A second hardcoded list here is the drift ADR 0091 is about, and it is the
drift that *produced* this defect: the predicate had its own idea of what a
request contains and it was never the request type's. A field added to
`CompletionRequest` tomorrow widens this predicate on the same commit, and
`test_the_routable_keywords_are_read_off_the_request_type` fails if anyone
replaces the derivation with a literal.

Any other keyword — `system`, `tools`, `stop_sequences`, `tool_choice`,
`thinking`, anything — makes the site **unrouted**, and the refusal names the
exact keywords. `system=` has its own reason, because it is not a tuning knob:
it is the instruction the adopter's behaviour depends on. Its reason says
precisely what is missing — no `system` field, and no basis for deciding how a
literal system prompt pairs with the objective this node substitutes — rather
than the broader and untrue "nowhere to put it".

**Follow-up not taken here.** A call whose *only* inexpressible keyword is a
literal `system=` string could be routed by emitting
`ProviderMessage(role="system", content=...)` ahead of the user turn, since
every adapter honours that role. It is not done in this fix: it is a semantic
choice about a node whose message list is already a substitution, it does not
help the reproduced case (`s9` also passes `tools=` and `stop_sequences=`), and
the direction of this wave is to refuse. Recorded so the option is not lost.

**Expressible is necessary, not sufficient.** The value must also be one this
command reproduces verbatim. `max_tokens=MAX` used to route as *no*
`max_tokens`, which silently substituted `CompletionRequest`'s default of
16000 for the adopter's cap — the same silent substitution as dropping
`system=`, one step quieter. Non-literal now refuses, naming the keyword.
Everything carried is emitted into the generated request in the request type's
own field order.

`stream` keeps its dedicated refusal above this rule; the only value that
reaches the keyword check is a literal `stream=False`, which routing preserves
exactly rather than drops.

### 2. Three more refusals, all in the same direction

- **Any decorator at all** → unrouted, naming it. A decorator can wrap the call
  in retry, caching, rate limiting or tracing that the body does not show, and
  this analysis reads bodies. This subsumes the accidental catch of
  `@retry(...)` and gives both forms the right reason.
- **`*args` or `**kwargs` at the SDK call** → unrouted. What a caller passes is
  not visible, so it cannot be shown to survive.
- **A client constructor with ANY argument** → unrouted, naming the arguments.
  It configures an endpoint, credential, timeout or retry policy that
  `Services.model_provider` resolves for itself.

The thin shape the ready loop measured still routes; a test asserts that, so
these refusals cannot quietly become "refuse everything" and undo ADR 0137.

### 3. `--force` backs up a file it did not generate

On `--force`, migrate renders first and compares. Identical means there is
nothing to preserve and no `.bak` is written (a backup per regeneration would
be noise). Different means somebody changed it: the existing bytes go to
`aef_migrated.py.bak` — `.bak.1`, `.bak.2`, … if one is already there, because
losing the first round of edits to save the second is the same failure one step
along — and `report()` says so on stdout, naming the path and what is in it.

**Not changed here, and needed:** `aef/harness/preflight.py`'s fix string for
the "model calls visible" obligation still prints a bare
`aef migrate --dir . --force`. That file belongs to another worker. The
requirement is stated in this ADR and in the final report: the fix string
should say that `--force` preserves an edited file as `.bak` rather than
implying the command is free.

### 4. A generated node that reaches a model is not pure

Every generated node — routed **and** unrouted, since both reach a model —
declares `side_effects=SideEffect.EXTERNAL_CALL` and supplies the
`idempotency_key_fn` the node contract then requires.

**The decision, and why it went this way rather than the TODO.** The
alternative was to emit the key commented out with a `TODO` so
`Node.__post_init__` raises and the adopter must choose. That refuses more, and
it was rejected: `build_graph()` would raise at import, so the generated module
would not run at all — and running it is the entire evidence chain ADR 0137
built (provider call → `RecordedCall` → credential-free replay) and what
`READY_LOOP.md` K3 depends on. A migration tool whose output cannot be executed
has not done the mechanical half.

The shape generated is the one this repo already uses for its own live model
call — `agents/summary/graph.py`'s `draft` node declares exactly
`side_effects=SideEffect.EXTERNAL_CALL` with a
`run_id`/node/`checkpoint_seq` key. Generating something else would be a second
house idiom. The key varies by run and checkpoint, so G4's constant-key finding
does not fire on it.

**What the key does not buy, stated in the generated file rather than here.**
`ModelProvider.complete()` accepts no idempotency key, so nothing downstream
deduplicates on this one: a second attempt is a second billed call returning a
different answer. The generated `_idempotency_key` factory carries a docstring
saying that, and saying that `add_bounded_retry` will now propose retrying the
node. The defect being fixed is that the guard was **never asked** — it read
PURE and moved on. It is asked now, and the node answers truthfully; whether an
adopter accepts a retry candidate on a billed call is their decision, made with
the declaration in front of them.

## After

```
$ aef migrate --dir .scratch/seam2/s9
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 0 routed through Services.model_provider, 1 still calling your function

  WRAPPED  agent.ask:4  (anthropic.Anthropic)
            -> calls agent.ask, unchanged
            NOT routed because it passes system= to the SDK (and stop_sequences=,
            tools=) — a system prompt is an instruction your code relies on, and
            CompletionRequest has no system field; carrying it would mean
            synthesising a system-role message to pair with the objective this
            node substitutes, which is a semantic decision migrate will not make
            for you
            the model call stays INVISIBLE to the harness: no policy check, no
            fallback, no RecordedCall to replay
```

```
$ scan .scratch/seam2/s1
UNROUTED  src.a_retry_decorated.ask_retry_bare
          it is decorated (@retry) — a decorator can wrap the call in retry,
          caching, rate limiting or tracing that the body does not show
UNROUTED  src.e_kwargs.ask_kwargs
          it forwards **kwargs into the SDK call — migrate cannot see what a
          caller passes, so a caller supplying stream=, system= or tools= at
          runtime would have it dropped without trace
UNROUTED  src.g_custom_client.ask_custom
          it configures its own client — anthropic.Anthropic(base_url=, timeout=,
          max_retries=) sets an endpoint, credential, timeout or retry policy that
          Services.model_provider resolves for itself, so routing would send this
          call somewhere else
```

```
$ aef migrate --dir .scratch/seam2/s2 --force      # with a hand edit in place
your existing aef_migrated.py DIFFERED from what migrate generates —
it was backed up to .../aef_migrated.py.bak before being overwritten.
If you had hand-edited it (re-expressed a system prompt, finished a
node body), that work is in the backup and not in the new file.
$ grep -c "HAND EDIT" aef_migrated.py.bak
1
```

```
node.side_effects      : external_call
idempotency key        : src_my_agent__run_agent:r1:0
retry with a key       : ACCEPTED (guard engaged, EXTERNAL_CALL + key)
retry without a key    : REFUSED — node 'src_my_agent__run_agent' is non-pure and
                         declares no idempotency_key_fn, so repeating its work is
                         not known to be safe
```

## Mutations — 10 planted, 10 caught, every one reverted

```
CAUGHT  M1  R1: routable keywords become a hardcoded list again      3 failed, 38 passed
CAUGHT  M2  R1: an inexpressible keyword no longer blocks routing    2 failed, 39 passed
CAUGHT  M3  R1: an expressible keyword may be non-literal            1 failed, 40 passed
CAUGHT  M4  R2: decorators no longer block routing                   2 failed, 39 passed
CAUGHT  M5  R2: **kwargs forwarding no longer blocks routing         2 failed, 39 passed
CAUGHT  M6  R2: a configured client no longer blocks routing         1 failed, 40 passed
CAUGHT  M7  R10: --force overwrites without a backup again           1 failed, 40 passed
CAUGHT  M8  R11: generated nodes go back to the PURE default         4 failed, 37 passed
CAUGHT  M9  R11: the key fn is dropped, node unbuildable             3 failed, 38 passed
CAUGHT  M10 R11: EXTERNAL_CALL downgraded to IO                      1 failed, 40 passed

$ git diff --exit-code       # after every revert
0
```

## A new defect found on the way

`test_a_long_node_id_keeps_the_generated_file_within_the_line_limit` was
written to prove the new `idempotency_key_fn=` line could not push the output
past 100 columns. It failed for three **pre-existing** reasons instead: with a
realistic module path (`src/services/llm/anthropic_backend_client.py` +
`call_llm_with_backend_and_budget`), the docstring's qualified-name lines and
the `return StateDelta(working_memory={"<node id>": ...})` line were already
116, 125 and 138 characters — in both node forms. ADR 0137 added a ruff test
over the generated output and ran it only on short names, so the E501s it
records finding were not all of them. The qualified name is now reflowed
through `_wrap`, the node id is bound to a local before use, and a long
`from <module> import <function>` wraps in parentheses.

## Consequences

- **The routable predicate now answers a second question**: not only "does the
  function do more than call" but "does the call ask for more than
  `CompletionRequest` holds". Both must be no.
- **`aef migrate` refuses more.** The measured toy adoptee still routes; the
  realistic shapes in `s1` and `s9` no longer do. That is the correct
  direction — an unrouted node is honestly labelled invisible and
  `aef loop doctor` refuses on it; a routed node that dropped a payout ceiling
  is found in production, by an adjuster.
- **A generated node can no longer claim to be pure**, so the loop's retry
  transformation evaluates it instead of skipping the question.
- **`--force` is no longer destructive**, which matters because a repo-level
  obligation prints it as the recommended fix.

## Confidence

**High** on all four reproductions and all four fixes: each was run before and
after, each is pinned by a test, and each test has a mutation behind it.

**High** on the anti-drift derivation. It is the mechanism ADR 0091 asks for,
and the test fails if a literal set replaces it.

**Medium** on `temperature`. It is a field of `CompletionRequest`, so it is
carried — but `aef/providers/anthropic_provider.py` documents that it does not
forward it, because current Anthropic models reject sampling parameters. So a
call site with `temperature=0.0` routes, the value reaches the request, and one
adapter drops it there. That is a gap between the request type and an adapter,
not between the call site and the request type; this predicate answers the
second question only. Named here so it is not discovered later. Closing it
would mean either a per-adapter capability declaration or excluding a real
field by hand, and the second is the drift this ADR is about.

**Medium** on completeness of the refusals. Four shapes were found by one seam
hunt over hand-written counter-shapes. The predicate is now conservative in a
way that is checkable — everything is refused unless it is a field of a
five-field dataclass with a literal value — but "what else does a real repo's
call site do" is still unmeasured, which is `READY_LOOP.md` K5's gap for the
whole loop.

**Not measured:** any repo but the toys. Same gap ADR 0137 recorded, unchanged.
