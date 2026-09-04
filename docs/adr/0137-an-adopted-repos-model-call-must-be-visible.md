# ADR 0137: An adopted repo's model call must be visible to the harness

## Status

Accepted. Increment K1 of `READY_LOOP.md`; record in `IMPROVE_LOG.md`.
**No rubric score moves** — this loop's definition of done is four
command-backed statements, not points. K1 makes statement 2 true and
statement 3 true of `aef loop doctor`.

## Context

`READY_LOOP.md` measured `aef adopt` then `aef migrate` on a fresh repo with
one real agent, and found the readiness blocker in the last line of the
report: *migrate did work — and the wrapper calls `run_agent(state.objective)`,
and `run_agent` still builds its own client.*

That is this repo's signature defect shape, a green light for something that
does not hold, and it was reproduced four ways before anything was changed.
The consequences are not stylistic. A node whose call never reaches
`Services.model_provider`:

- is not seen by the policy engine, so constraint #6 governs nothing about it;
- is not covered by `FallbackProvider`, so the vendor-neutrality mechanism
  does not apply to the one call that matters;
- still needs the adopter's own API key, which is precisely what ADR 0112's
  harness login exists to remove;
- and — the expensive one — is **invisible to `aef/harness/recorder.py`**, so
  the scenario recorded from it carries no `RecordedCall`. Replay under
  `on_miss="fail"` then has nothing to serve *and nothing to refuse*: the gate
  reaches the vendor live, or fails for want of a credential and scores 0.

The detector for this already existed and had run on every push since Phase 0.
`tests/test_vendor_isolation.py` AST-scans for vendor SDK imports and enforces
constraint #3 — but it lives in `tests/`, so it can only ever scan *this*
repo. The rule it encodes is not a house style; it is the same rule, and
nothing had ever pointed it at an adopter.

## Decision

### 1. Lift the scanner into `aef/`, one list and one scanner

`aef/harness/vendor_scan.py` holds `VENDOR_TOP_LEVEL_MODULES` (the constraint
#3 list, moved verbatim), `MODEL_SDK_ROOTS` (the strict subset `aef migrate`
uses to recognise a *model* call — `opentelemetry` is a vendor SDK and is not
one), and `scan_source`/`scan_file`/`scan_tree`.
`tests/test_vendor_isolation.py` imports it back and keeps every one of its
regression tests. `aef/cli/migrate.py` deletes its own `_VENDOR_ROOTS` tuple
and imports the shared one. A second list of vendor module names is the drift
ADR 0091 is about, and a test asserts `MODEL_SDK_ROOTS <=
VENDOR_TOP_LEVEL_MODULES` so the two cannot separate.

**That subset test failed on its first run.** `cohere` was in `migrate.py`'s
tuple and had never been in the constraint #3 list — `import cohere` in
`aef/kernel/` would not have been caught. The drift the test was written to
prevent was already present. Added to the list; a mutation removing it again
fails the test.

### 2. A sixth preflight obligation: **model calls visible**

`preflight()` walks the modules reachable by import from the configured graph
(`repo_root / agent_path`, transitively, following only files that resolve
*inside the repo*) and scans each with the lifted scanner. A reachable module
that imports a vendor SDK is an unmet obligation, named with the file, line
and vendor, and its fix names the call that replaces the client. It appears in
`aef loop doctor` alongside the existing five, and `Preflight.ready` is false
while it stands, so the gates refuse.

`aef doctor` gains the same finding as an **advisory** when `aef_migrated.py`
exists. Advisory rather than error because "is this setup coherent" is
`aef doctor`'s question and "is this repo ready to be gated" is `aef loop
doctor`'s; an adopter mid-migration is not broken. The point is that the
surface stops saying nothing.

### 3. `aef migrate` generates the routed form when it can, and says why

Two forms, chosen by reading the function, and named in both the report and
the generated node's own docstring:

- **routed** — `services.require_model_provider().complete(...)`, and the
  adopter's function is **not called**. The report says it is now bypassed and
  that its retries and backend selection are the adopter's to re-express.
- **unrouted** — today's wrapper, plus a docstring warning that this call does
  not pass through `Services.model_provider`, that the recorder captures no
  `RecordedCall` for it, and that `on_miss="fail"` will therefore either reach
  the vendor live or score the scenario 0.

Routed is generated only when the function is nothing but the call: its own
body constructs the client (not injected, not global), it makes exactly one
recognised completion call carrying a **literal** model id, and it contains no
loop, no `try`, no stream and no other calls. The literal `model=` and
`max_tokens=` are carried into the generated `CompletionRequest`, so no model
id is invented.

### 4. The falsification clause, and which way it was decided

`READY_LOOP.md` asks: if routing loses something the adopter's function had,
generate the unrouted form with a warning and say so.

**Decided by reading the code, in favour of the unrouted form for every case
where anything at all is in the way**, and the decision rule *is* the
falsification test. `ModelProvider.complete()` is one shot, non-streaming, and
single-backend. A `for` loop is a retry or backoff policy; a `try` is a
fallback policy; `stream=True` changes the shape of the answer the caller
reads; a non-literal model id means we would be guessing; any other call in
the body means the function does something we cannot see through. Each of
those is strictly more than `complete()` offers, so routing them is a silent
rewrite, not plumbing. Each is a separate `_Routing(False, <reason>)` naming
what would have been dropped, and each has its own test.

The transitive case matters most and is the one the module was already built
around: `_scan_module` deliberately chooses the **outermost** wrapper, because
that is where a real repo keeps its retries, budgets and backend order (the
defect its own docstring records). That function is still the right one to
*wrap* and is exactly the wrong one to *route* — so evidence marked
`(transitively)` is never routed.

The conservative direction is deliberate. A wrapper honestly labelled invisible
is recoverable — `aef loop doctor` refuses on it and the adopter reads why. A
rewrite that quietly dropped a retry policy is found in production.

The adoptee measured by `READY_LOOP.md` **is** the thin shape, so it routes;
that is a fact about that repo, not a claim about repos in general.

## Evidence

All commands run from the worktree; `PYTHONPATH` and the venv elided.

### Reproduced first, before any change

**R1 — `aef doctor` reports green.** On the adopted+migrated repo:

```
$ aef doctor --dir <adoptee>
[OK] python_version: 3.13 (need >=3.11)
[OK] claude_md_present: .../CLAUDE.md
[WARN] adapter_importable: ... — still the generated stub, not wired yet
[OK] agent_config:.../aef.yaml: valid
[WARN] advisory:...:empty_objectives: ...
EXIT=0
```

Exit 0. Two advisories, neither about the model call.

**R2 — the migrated node's call bypasses `Services.model_provider`.** The
generated node run against a counting provider, with a fake `anthropic` module
installed so nothing live is called:

```
node                     : src_my_agent__run_agent
vendor SDK reached       : ['anthropic.Anthropic()', 'client.messages.create']
Services.model_provider  : 0 call(s)
node result              : {'src_my_agent__run_agent': 'vendor answered'}
```

**R3 — no `RecordedCall`, so `on_miss="fail"` cannot replay it.**
`record_run` on the same graph, then `run_scenario(..., cassette_miss="fail",
live_provider=None)`:

```
recorded scenario s1     : 0 RecordedCall(s)
live vendor calls during recording: ['LIVE client.messages.create']
replay score             : 0.5   node_path=['src_my_agent__run_agent']
live vendor calls during REPLAY   : ['LIVE client.messages.create']
replay, no vendor SDK    : score=0.0
    failure: 'TypeError: "Could not resolve authentication method..."'
    cassette: {'hits': 0, 'misses': 0}
```

Exactly the disjunction `READY_LOOP.md` predicted: **a live call inside a gate
that was told not to make one**, or 0. Note `misses: 0` — the cassette does not
even record a miss, because the call never reached it. `on_miss="fail"` is not
bypassed by a bug in the cassette; it is bypassed by never being asked.

**R4 — nothing warns.** `aef loop doctor` listed five obligations, all about
corpus/reflect/observations/halt/baseline. `aef migrate`'s report:
`found 1 call site(s): 1 wrapped, 0 skipped` and a closing paragraph about
semantics. `aef doctor`: above. No surface mentioned the bypass.

### After

```
$ aef loop doctor --repo . --state .aef-state --agent-path aef_migrated.py ...
Loop readiness — 6 things you must supply
  ...
  [--] model calls visible     src/my_agent.py:1 imports anthropic
                               — the harness cannot see it
       fix: aef migrate --dir . --force. Route the call through the container:
       `services.require_model_provider().complete(...)` ... the recorder
       captures no RecordedCall for it — so the gates replay nothing and
       either call the vendor live or score it 0.
EXIT=1
```

```
$ aef migrate --dir . --force
scanned 3 Python file(s)
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 1 routed through Services.model_provider, 0 still calling your function

  ROUTED   src.my_agent.run_agent:2  (anthropic.Anthropic)
            -> services.require_model_provider().complete(model='claude-sonnet-4-6')
            routed because its body builds the client and makes exactly one
            completion call, with no loop, no try/except and no stream —
            there is nothing here for routing to lose
            src.my_agent.run_agent is now BYPASSED — its retries and backend
            selection are yours to re-express
```

The same four questions, asked again of the routed node:

```
Services.model_provider  : 1 call(s)
vendor SDK reached       : []
recorded scenario s1     : 1 RecordedCall(s)
replay, no vendor SDK    : score=0.5  cassette={'hits': 1, 'misses': 0}
live vendor calls during REPLAY   : []
```

The gate now replays the scenario **with the vendor SDK deleted from
`sys.modules` and no credential anywhere**, scores it identically to the live
run, and makes no network call. And:

```
$ aef loop doctor ...
  [OK] model calls visible     1 reachable module(s), none imports a model SDK
```

### Mutations — 8 planted, 8 caught, every one reverted

```
CAUGHT  M1 preflight: the vendor scan reports nothing        3 failed, 34 passed
CAUGHT  M2 preflight: reachability stops at the entry file   1 failed, 18 passed
CAUGHT  M3 migrate: everything declared routable             1 failed, 24 passed
CAUGHT  M4 migrate: try/except no longer blocks routing      2 failed, 23 passed
CAUGHT  M5 migrate: routed node bypasses require_...()       1 failed, 24 passed
CAUGHT  M6 migrate: _skip tests the ABSOLUTE path again      1 failed, 24 passed
CAUGHT  M7 vendor_scan: cohere drops out of the list         1 failed, 10 passed
CAUGHT  M8 vendor_scan: scanner ignores nested imports       3 failed,  8 passed

$ git diff --exit-code      # working tree vs the staged work
0   (every mutation reverted byte-for-byte)
```

### Green bar

```
pytest -q          1847 passed, 1 skipped  (+27 tests, none removed)
mypy aef examples  128 files clean
ruff check .       clean
ruff format --check aef tests examples   236 files already formatted
calls made: 0 — no live model call anywhere in this increment
```

## Consequences

- **An adopter can no longer be told they are ready when the gates cannot
  replay them.** `aef loop doctor` refuses; `aef doctor` warns; `aef migrate`
  says which form it chose and what the other one would have cost.
- **Constraint #3 is now one mechanism instead of a house rule plus a test.**
  It scans this repo's banned zones and an adopter's graph with the same code
  and the same list.
- **A repo whose every call site is unroutable still gets no green light,** and
  that is correct: the obligation is *visible*, not *routed*. Routing such a
  function is a decision only its owner can make, and the fix string says so.
- **A new defect was found on the way and fixed here**, because K1's own
  reproduction could not run without it. `migrate._skip` tested the
  **absolute** path against a dot-directory denylist, so a repo living anywhere
  under a dot-directory — `~/.local/src/app`, a git worktree under `.claude/`,
  a checkout in `.build/` — had *every* file skipped and reported
  `scanned 0 Python file(s) ... 0 call site(s)`, exit 0. Reproduced with two
  identical repos differing only in location (1 site vs 0). The dot-directory
  rule was written for `.codex/worktrees/` duplicates *inside* a repo and
  still applies there; both halves are asserted. This is the same defect class
  as the one K1 is about — a tool reporting success for a question it declined
  to ask.
- **Three lint failures in generated output**, also found here: the generated
  module never passed the repo's own ruff (`E501` on the `def` line and the
  `Node(...)` line, `F401` on an `Any`/`Graph` import block the empty form
  never used). Nobody had run ruff on the output. Now a test does, for all
  three forms, and another executes both node forms to prove the imports
  resolve and `build_graph()` builds.

## Confidence

**High** on the four reproductions and on the routed path end to end: the
provider call, the captured `RecordedCall`, and the credential-free replay were
each executed and are each pinned by a test with a mutation behind it.

**High** on the routing decision being conservative in the right direction —
every blocker is a specific AST feature with its own test, and the default when
migrate cannot tell is the old behaviour plus a warning.

**Medium** on the decision being conservative *enough for real repos*. The
routable predicate was designed against one eight-line adoptee and seven
hand-written counter-shapes. A function that is a thin wrapper by these rules
and still does something meaningful — a decorator applying a retry, a client
constructed with a custom `base_url` or timeout, a module-level `httpx` client
handed to the SDK — would be routed and would lose it. The decorator case in
particular is invisible to this analysis, which reads only the function body.

**Medium** on the reachability walk. It resolves absolute imports against the
repo root, which is where `aef run <module>` and the generated node resolve
from, and it does not resolve `sys.path` manipulation, namespace packages, src
layouts rooted elsewhere, or dynamic `importlib` imports. A repo using any of
those can hide a vendor import from this obligation. It over-reports nothing
(a false positive requires a real vendor import in a real reachable file) and
can under-report, which is the safer failure for a check that gates.

**Not measured:** any repo but the toy. The scanner has never run against a
codebase nobody wrote to be scanned, which is the same gap
`READY_LOOP.md` K5 names for the whole loop.

## Erratum (ADR 0140, fix wave C)

Two claims in this ADR were wrong, and a seam hunt reproduced four defects in
the routed form it shipped. The corrections, in the order they matter:

**1. "There is nothing here for routing to lose" was false, and the generated
node said it out loud.** Section 3 above defines routable as: own client, one
recognised completion call, literal `model=`, no loop, no `try`, no stream, no
other calls. Every one of those conditions is about **control flow**. Nothing
in the predicate ever looked at the *keywords the call passes*, and
`CompletionRequest` has five fields — `messages`, `model`, `max_tokens`,
`temperature`, `metadata`. Reproduced: a call site passing
`system="You are a claims adjuster. NEVER approve a payout above $5,000."`
together with `tools=`, `stop_sequences=` and `temperature=0.0` was judged
ROUTED, and the generated node carried `messages/model/max_tokens` only. The
payout ceiling and the tool grant were dropped, and the node's docstring told
the reader that nothing had been.

**2. The falsification clause was incomplete in kind, not merely in coverage.**
Section 4 enumerates retries, loops, `try`, streams, guessed models and
transitive wrappers, and concludes with the decision rule *"anything at all in
the way"*. It asked only whether the FUNCTION does more than call. It never
asked whether the REQUEST survives translation into `CompletionRequest`. Those
are two different questions and only one of them was answered. The clause now
covers both (ADR 0140): the routable keyword set is derived from
`dataclasses.fields(CompletionRequest)`, so any keyword the request type cannot
carry — and any expressible keyword whose value is not a literal this command
reproduces verbatim, `max_tokens=MAX` included — refuses the routed form and
names itself.

**3. Two shapes this ADR's own Confidence section predicted, and shipped
anyway.** It reads: *"a decorator applying a retry, a client constructed with a
custom `base_url` or timeout ... would be routed and would lose it. The
decorator case in particular is invisible to this analysis."* Both were then
reproduced as real routes — a bare `@retry` (an `ast.Name`, invisible even to
the "body also calls `retry()`" rule, which caught the *called* form only by
accident) and
`anthropic.Anthropic(base_url="https://llm-gateway.corp/v1", timeout=120.0,
max_retries=8)`, which routed a call to a different endpoint, credential and
account. A third, unpredicted: `**kwargs` forwarded into the SDK call is an
`ast.keyword` with `arg=None`, filtered out before any keyword was read, so a
caller passing `stream=True` at runtime defeated the stream check. All three
now refuse, each with its own reason and its own test. A predicted defect that
ships is a defect, not a caveat.

**4. `--force`, which this ADR's own fix string recommends, discarded edits.**
The "model calls visible" obligation prints `aef migrate --dir . --force`.
Reproduced: hand-edit the generated node, run that line, edits gone — no
backup, no diff, no warning, exit 0, three lines below a comment calling an
edited generated file "the expensive thing to lose". `--force` now writes a
`.bak` and says so whenever the existing file differs from what migrate would
generate.

**5. Every generated node declared `side_effects` PURE.** `render()` emitted
`Node(...)` with no `side_effects`, so the default applied — a live routed
model call declared to have no effect on the world. `add_bounded_retry`'s guard
skips its idempotency requirement entirely when the declaration is *absent*, so
the loop could wrap that call in a 3-attempt retry with nothing asked. Both
generated forms now declare `SideEffect.EXTERNAL_CALL` with a generated
`idempotency_key_fn`.

**6. The generated output still failed the repo's own ruff.** The "three lint
failures in generated output" this ADR records finding were the ones a short
node id produces. With a realistic module path the docstring's qualified-name
lines and the `working_memory={"<node id>": ...}` line are 116, 125 and 138
characters, in both forms. The ruff test added here only ever ran on short
names; ADR 0140 adds a long-name case and reflows the output.

Nothing else in this ADR is retracted: the four reproductions, the lifted
scanner, the sixth preflight obligation, and the routed path's end-to-end
evidence (provider call → `RecordedCall` → credential-free replay) all stand,
and the thin adoptee measured here still routes.

## Erratum, 2026-09-04 (ADR 0141, fix wave D)

Three statements above are false as written. They are left in place — this is a
dated record — and corrected here.

**1. "It over-reports nothing (a false positive requires a real vendor import in
a real reachable file)" (Confidence, on the reachability walk).** False for 14
of the 19 names. §1 says the obligation reuses the lifted scanner, and the
scanner's default list is `VENDOR_TOP_LEVEL_MODULES` — the constraint #3
question — not `MODEL_SDK_ROOTS`, which is the question the obligation is
about. So `import psycopg2` in a reachable module was an unmet obligation, and
the printed fix told the adopter to route a Postgres connection through
`services.require_model_provider().complete(...)`. Reproduced:

```
>>> model_calls_are_visible(Path("repo"), "mygraph.py")   # db.py: import psycopg2
(False, 'db.py:1 imports psycopg2 (+2 more) — the harness cannot see it')
```

`scan_*` now takes `roots`; the obligation passes `MODEL_SDK_ROOTS`;
constraint #3 keeps the full list. `google` remains in `MODEL_SDK_ROOTS` and
remains blocking, which is the trade `vendor_scan.py` already documented.

**2. "`Preflight.ready` is false while it stands, so the gates refuse" (§2).**
False. `Preflight.ready` had exactly one reader in `aef/`: `cmd_doctor`.
Reproduced — `aef loop doctor` exit 1 with obligation 6 red, then `aef loop
cycle` on the same repo proposed and gated. ADR 0141 decided the obligations
are **advisory**, with the reasoning stated there (a refusal could live only in
the CLI, so the importable `harness.loop.cycle()` would stay unguarded and this
sentence would still be false), corrected `Preflight.render()`'s matching claim,
and made `cycle`/`gate` print the unmet obligations before running.

**3. "`aef doctor` gains the same finding as an advisory when `aef_migrated.py`
exists" (§2) — accurate as a description, and the design was wrong.** That is
the artefact of a different command. A repo that followed the documented
adoption path (`aef adopt`, wire `aef_adapter.py`, nodes under `agents/**`) has
no `aef_migrated.py`, so the advisory could not fire for the only path the docs
describe; reproduced with `agents/mine/vendor_helper.py` importing `anthropic`
and `aef doctor` saying nothing. The advisory is now keyed on the configured
graph, with `--agent-path` on `aef doctor`.

Also corrected there: the obligation's `fix:` string was `aef migrate --dir .
--force` for every unmet case, including the unroutable population §4's
falsification clause deliberately creates — running it regenerates the identical
wrapper and leaves the obligation byte-identically red.
