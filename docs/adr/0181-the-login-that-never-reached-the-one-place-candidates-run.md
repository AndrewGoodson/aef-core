# ADR 0181: The login that never reached the one place candidates run

## Status

Accepted. Fix worker **K1** of `UPGRADE_LOOP.md`. Model: `claude-opus-5[1m]`.
**18 live model calls** (budget ≤ 30): 1 quota preflight, 3 environment
probes, 14 inside the live proof. **No rubric dimension moves** — this closes
two defects and adds one opt-in; it measures no learning.

Closes ADR 0158's two HIGH findings, **F-M5-2** and **F-M5-3**. Together they
meant that *no provider served a live cassette miss inside the gates*, on any
repo, ever — so `UPGRADE_LOOP.md`'s rule

> A prompt candidate is gated live, or not at all.

resolved to **not at all**, everywhere, every time. That rule is true for the
first time as of this branch, and the last section of this ADR is the run that
makes it true.

---

## The decision M5 asked for

M5 was explicit that F-M5-3's fix "is one word but deserves a decision", and
its reasoning is the whole of this section:

> the allowlist exists so no credential is inherited, and adding `USER` is how
> the shadow run gains the operator's quota.

Both halves of that are correct, and they point in opposite directions.
`sandbox.py`'s own docstring says the first thing it enforces is an
"environment scrubbed to an explicit allowlist (no credentials inherited)",
and the gates' worker is *the one process in this repo that executes code an
agent wrote*. The trust case's whole containment argument runs through it. So
`claude -p` answering `Not logged in` in there is the allowlist **working**.

And yet ADR 0112's premise — the one on the first line of every generated
`aef.yaml` — is that the coding agent's own login *is* the credential, no API
key anywhere. That premise held in the parent process, which is why
`bootstrap` records live without complaint, and did not hold in the worker.
The credential never reached the one place candidates run.

**The decision: live model calls inside the gates are an explicit per-repo
opt-in, off by default.**

```yaml
# aef.yaml
gates:
  live_model_calls: false   # the default; the field may simply be absent
```

- **When false** — the default, and what every existing repo gets without
  editing anything — the worker's environment allowlist is byte-for-byte what
  it was before this branch. No login, no credential, and a candidate's code
  cannot spend the operator's quota. That is the containment property, and it
  stays the default.
- **When true** the worker's allowlist gains `sandbox.HARNESS_LOGIN_ENV`, and
  every `gated` ledger event records `live_model_calls: true`, so a reader of
  the audit trail can see which gate passes ran candidates under the
  operator's login.
- **`--cassette-miss live` with the opt-in false is REFUSED by name**, before
  a proposal is journalled:

```
error: live gating is off in aef.yaml; a prompt candidate cannot be scored
from a cassette — set gates.live_model_calls: true, which lets a candidate's
code spend your harness quota. Until then `--cassette-miss live` is refused
rather than run: without the opt-in the gate's worker inherits no login,
every miss fails, and G2 reports that as 'previously-passing scenario(s) no
longer pass' — an artifact of the environment rather than a judgement of the
prompt (ADR 0158, ADR 0181).
```

The refusal matters as much as the widening. What ADR 0158 measured live was
a `G2 fail — 2 previously-passing scenario(s) no longer pass`, and that
sentence is a lie about the prompt: the scenarios failed because a
subprocess could not log in. A flag that quietly produces a wrong verdict is
worse than a flag that refuses, which is this repo's standing rule (ADR
0090's "a policy that quietly does not apply is worse than one that
refuses") applied one layer out.

Three properties of the opt-in are deliberate:

1. **It lives in `aef.yaml`, not in a CLI flag.** Whether a repo's owner
   accepts that gate runs spend their quota is a property of the repo, not of
   one invocation, and a flag is something a scheduled workflow acquires by
   copy-paste.
2. **It is read from the BASE REF**, exactly as `policies` and `tools` are
   (ADR 0082). A candidate that could turn this on in its own branch would be
   handing itself the operator's login — the same argument that makes the
   policy engine read the base ref, with a sharper consequence.
   `test_the_opt_in_is_read_from_the_base_ref_not_the_working_tree` pins it.
3. **The name says the consequence.** `gates.live_model_calls` — not
   `gates.allow_network`, not `gates.online`. What is being permitted is
   *model calls made by candidate code, billed to you*, and the docstring
   says so in the owner's own words.

### The variables the login needs, measured

The one-word patch was not applied blind. Five probes of the **exact argv**
`ClaudeCodeProvider` builds (`claude -p --no-session-persistence
--output-format json --max-turns 1 --tools "" --strict-mcp-config
--mcp-config '{"mcpServers":{}}' --safe-mode --model claude-opus-5
--system-prompt … OK`), each with a hand-built environment, on macOS 25.4 with
`claude` 2.1.x:

| environment | rc | `is_error` | `result` |
|---|---|---|---|
| `DEFAULT_ENV_ALLOWLIST` as shipped | 1 | true | `Not logged in · Please run /login` |
| allowlist + `LOGNAME` | 1 | true | `Not logged in · Please run /login` |
| allowlist + `USER` | 0 | false | `OK` (447 in, 4 out) |
| allowlist − `HOME`, + `USER` | 0 | false | `OK` |
| `PATH` + `USER` **only** | 0 | false | `OK` |

So it is **`USER`, and only `USER`**:

- not `HOME` — dropping it entirely still logs in, so the credential is not
  read out of the config directory; the keychain is reached as the same uid
  and needs no variable;
- not `LOGNAME` — the other conventional spelling of the identical fact does
  **not** substitute, which is exactly ADR 0150's lesson (a name's *spelling*
  is not its semantics) and the reason this table exists instead of a guess.

Only the three failing rows plus two successes were run; a `Not logged in`
answer exits in ~30 ms without reaching the API and costs nothing, so the
measurement cost **3 billed calls**. `HARNESS_LOGIN_ENV = frozenset({"USER"})`
carries the table in its docstring, next to the code it justifies.

A harness on another platform whose login needs more than this fails the same
visible way it fails today — a `ModelProviderError` quoting the CLI's own
message — rather than silently.

---

## F-M5-2: the credential-free provider could not cross either

`_live_provider_from_base_ref` put `{"impl", "model"}` on the wire and
`node_worker._configure` rebuilt `ModelProviderConfig(impl=…, model=…)` from
it. For `impl: command` the schema refused, **correctly**:

```
IsolationError: worker refused configuration: configure failed:
  ValidationError: … model_provider.impl is 'command' but no `command:` block
  is present. There is no argv template to run; see docs/adr/0154.
```

Every scenario, every cohort member. So the one provider that needs **no
credential at all** — and the one ADR 0154 points every new adopter at — was
the one provider a live gate pass could not use.

`ModelProviderConfig` is *data*: a strict pydantic model that round-trips
through `model_dump(mode="json")`, which is what the framed protocol already
carries. So the whole block crosses now, and the worker rebuilds it with
`ModelProviderConfig.model_validate(live)`. The argv template, the
`system_argv` slot, the output pointer, the `isolation:` assertion (ADR 0169's
owner claim) and the `fallback:` chain all survive.

Two fixes in one function, and they are the same fix: what crosses the
boundary should be the configuration the owner wrote, not a hand-picked subset
of it, and what the process on the far side is allowed to do with it should be
something the owner said yes to.

### The round-trip, proved rather than asserted

`tests/harness/test_live_gating.py` builds a repo whose base ref declares

```yaml
model_provider:
  impl: command
  model: stub-echo
  command:
    argv: ["/bin/echo", "{system}", "{prompt}"]
    system_argv: ["{system}"]
    isolation: ["no_tools", "single_turn"]
```

and then:

- `test_the_whole_model_provider_block_crosses_the_wire` — the spec survives
  `json.dumps`/`loads` with `command.argv` and `command.isolation` intact;
- `test_a_command_provider_rebuilds_inside_the_worker_and_answers` — the
  rebuilt object is a real `CommandProvider` and answers a real
  `CompletionRequest` through a real subprocess;
- `test_a_live_miss_is_served_inside_the_worker_by_the_rebuilt_provider`
  (**the seam**) — a scenario whose model call is *not* in the cassette runs
  through `run_corpus_isolated` under `cassette_miss="live"`, and the miss is
  served **inside the worker** by the provider the worker built. Before this
  branch that call returned `IsolationError: worker refused configuration`;
- `test_the_same_miss_fails_when_no_provider_crosses` — the control, because a
  live-gating test that passed either way would be measuring nothing;
- `test_a_claude_code_config_round_trips_without_making_a_call` — the default
  provider crosses too: `default_model` survives, the argv still carries
  `--safe-mode`, and `isolation` matches a locally constructed adapter. No
  call is made.

`ClaudeCodeProvider` was rebuildable from `{impl, model}` all along; it is
covered here anyway, because "the two fields happen to be enough for this one
provider" is the property that broke.

---

## Where the widening is applied, and where it is not

```python
def _worker_sandbox_policy(config, live_provider):
    policy = config.sandbox_policy()
    if live_provider is None:
        return policy
    return with_harness_login(policy)
```

Tied to `live_provider`, not to `cassette_miss` alone. With no `--config`
there is no provider for the worker to build, so widening the allowlist would
inherit a credential for calls nothing can make — a leak with no purpose.
`_live_provider_from_base_ref` is called **once** at the gate site and its
result feeds both the provider and the environment, because computing them
apart is precisely how the two could disagree (ADR 0091's standing shape).

`with_harness_login` is a named function rather than an inline `|` at one call
site, so a reader grepping for *how does a credential reach the worker* lands
on a docstring instead of a set literal. It returns a copy: `SandboxPolicy` is
frozen, and no caller's policy becomes credential-carrying behind its back.

**`DEFAULT_ENV_ALLOWLIST` is unchanged.** Two tests say so out loud — the
converted `test_the_sandbox_env_allowlist_carries_what_the_harness_login_needs`
and `test_the_default_allowlist_still_inherits_no_login` — because the obvious
"fix" for F-M5-3 is to add one word to that line, and that would let every
gate pass on every repo spend the operator's quota with nobody asked.

---

## The live proof

A copy of the pilot clone (read-only; `UPGRADE_LOOP.md`'s rule is that nothing
outside `aef-core` is written to, and a clone is not an exception), with
`gates: {live_model_calls: true}` in its `aef.yaml`, through the M5 sequence:
`adopt` → `migrate` → `bootstrap --memory --config` → `bless` → `cycle
--cassette-miss live --config aef.yaml --proposer rule_based_prompt`.

```
proposed cycle-20260905T071602-prompt on local branch
  loop/cycle-20260905T071602-prompt (never pushed; proposer=rule_based_prompt)
gated: reject — G3 rejected it: candidate does not beat the p95 of the random
  control cohort — this is the null hypothesis, not an improvement
```

The `gated` ledger entry:

```
live_model_calls: True
proposer: rule_based_prompt
evidence: 7 corpus pass(es) (14 scenario execution(s)): 1 candidate +
          1 incumbent + 5 random control(s); 2/2 gated scenario(s) recorded
          from graph 'marlin-accela'
G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically
         scanned, no violations; 1 NOT statically scanned (not Python …)
G1 pass  1 build command(s) succeeded against the merged workspace
G4 pass  no owner-only safety metadata declared by the candidate
G5 pass  0/3 accepted in the last 7d; drift 0.007/0.500 from the blessed baseline
G2 pass  2 scenario(s) re-executed; every previously-passing one still passes.
         0 changed routing (reported, not rejected).
G3 fail  candidate does not beat the p95 of the random control cohort — this
         is the null hypothesis, not an improvement
kinds: ['blessed', 'proposed', 'gated', 'rejected']
```

**Verdict: REJECT, by G3. Drift consumed: 0.007 of 0.500. 14 scenario
executions, 12 of them live cassette misses served inside the gates' worker.**

Read against ADR 0158's live half, which is the same repo, the same persona,
the same proposer and the same flag:

| | ADR 0158 | here |
|---|---|---|
| G2 | **fail** — 2 previously-passing scenario(s) no longer pass | **pass** — 2 re-executed, every previously-passing one still passes |
| G3 | never ran (G2 rejected first) | **fail** — does not beat the cohort's p95 |
| why | 29 `claude -p` invocations exited in ~30 ms with `Not logged in` | 12 live completions, served |
| the verdict is | an artifact of the environment | a judgement of the prompt |
| whole pass took | 20 s | 115 s |

That is the finding. **The rejection is the same word and a completely
different claim.** Before, G2 was reporting a subprocess that could not log
in; now G2 has *executed the candidate persona against real model calls* and
found no regression, and G3 has compared it against five prose controls and
found it inside the null. The candidate is rejected because the lesson did not
help, which is what a gate is for — and it is consistent with ADR 0158's
own paired `loop score` measurement (0.0000 → 0.0000) and with ADR 0157's
falsification: a rule-based lesson whose evidence is redacted (ADR 0174)
carries nothing a `contains` check can act on. **This branch fixes the
apparatus, not the learning**, and the two should not be confused.

The rejection also means the acceptance path itself is still unexercised end
to end: no candidate has been ACCEPTED live. Accept or reject was declared
acceptable proof in advance precisely so this ADR could not be written by
tuning until something passed — and nothing was tuned. What is now true, and
was not, is that acceptance is *reachable*: every gate ran, on live evidence,
and G3's arithmetic was the thing that said no.

**Calls, counted honestly: 18.** 1 quota preflight (`is_error: false`,
`result: "OK"`, 447 in / 4 out, `claude-opus-5`), 3 environment probes (the
two successful widened rows plus the `PATH + USER` minimum; the two failing
rows billed nothing), 2 bootstrap recordings, 12 gate executions (candidate ×2
and five controls ×2 all missed the cassette; the incumbent's two calls hit
it, which is the cassette doing its job).

---

## What this makes true for the first time

`UPGRADE_LOOP.md` says a prompt candidate is gated live or not at all, and
`CLAUDE.md` repeats it. Until this branch that sentence described an intention:
the flag existed, the code path existed, and no provider could reach the end
of it. Two commands could produce a live *score* (`aef loop score`, in-process,
ADR 0158's fallback) but the **gates** could not, and the gates are what decide.

So the rule is not new and neither is the flag — what is new is that the
sentence is now checkable, by `test_a_real_prompt_repo_gates_a_prompt_candidate_live`,
which asserts `live_model_calls is True`, asserts real executions in the
evidence line, and asserts that neither `worker refused configuration` nor
`Not logged in` appears anywhere in the run. Those last two assertions exist
because both defects reached G2 as an ordinary regression: **the exit code and
the verdict cannot distinguish a live gate pass from the two defects that made
one impossible.** A test that checked only "a verdict was reached" was green
throughout ADR 0158, and was right to be — it was pinning a different claim.

No rubric dimension moves. This is apparatus.

---

## Mutation results

Six mutations, each applied to a byte backup whose sha256 was verified before
and after restore (never `git checkout --`), each asserting its anchor was
found so a silent no-op patch could not read as "fixed":

| # | mutation | result |
|---|---|---|
| M1 | `live_model_calls` defaults to **true** | 3 tests FAIL |
| M2 | `DEFAULT_ENV_ALLOWLIST` gains `USER` (the one-word patch M5 warned against) | 3 tests FAIL |
| M3 | the `gated` ledger detail drops `live_model_calls` | 2 tests FAIL |
| M4 | `_live_provider_from_base_ref` returns `{impl, model}` again (F-M5-2 restored) | 3 tests FAIL |
| M5 | `node_worker` rebuilds from two fields again | 2 tests FAIL |
| M6 | the login widening is applied unconditionally | 1 test FAILS |

Every restore verified identical; the suite green again after all six.

## Green bar

```
pytest -q                              2700 passed, 7 skipped, 1 xfailed
                                       (2708 collected, from 2689 — +19, none
                                        removed: 19 new in test_live_gating.py,
                                        and the 2 strict xfails became passing
                                        tests rather than being deleted)
mypy aef examples                      135 files, clean
ruff check .                           All checks passed!
ruff format --check aef tests examples 280 files already formatted
```

The one remaining strict xfail in `tests/cli/test_prompt_repo_acceptance.py`
is **F-M5-1** (obligation 6's every-graph scan, unreachable under a widened
root), which is not this worker's.

## For the adopting repo's `FIRST_DAY.md`

`aef adopt` is not this worker's file. The line the generated document needs,
for M7 to place:

> **Scoring a prompt change costs real model calls, and it is off until you
> say otherwise.** A changed prompt is a changed cassette key, so replay
> scores it 0 — an artifact, not a verdict — and the only honest way to gate
> one is `aef loop cycle --cassette-miss live`. That runs your candidate's
> model calls under **your** harness login, inside the sandbox that executes
> agent-written code, so it is off by default: set `gates.live_model_calls:
> true` in `aef.yaml` to allow it, knowing a candidate's code can then spend
> your quota. Until you do, `--cassette-miss live` is refused by name rather
> than quietly rejecting every candidate. Every gate run records
> `live_model_calls` in the ledger, so you can always see which passes spent
> it.

## Errata

**ADR 0158** — F-M5-2 and F-M5-3 are **closed** by this ADR, and their two
strict xfails in `tests/cli/test_prompt_repo_acceptance.py` are passing tests
now. 0158's sentence *"no provider serves a live cassette miss inside the
gates today"* was true when written and is false as of this branch; its
"today" is doing real work and should be read as 2026-09-04. Its live-half
conclusion — `G2 fail — 2 previously-passing scenario(s) no longer pass` — was
an artifact of F-M5-3 and is superseded by the run above, where the same
sequence reaches `G2 pass` and is rejected by G3 instead. Its F-M5-1 stands.
Its paired `aef loop score` measurement (0.0000 → 0.0000) stands and is
corroborated: G3's cohort comparison reaches the same conclusion by a
different route.

**ADR 0112** — the premise "the coding agent's own login IS the credential; no
API key anywhere" was true of every process this repo spawned **except the
one that runs candidate code**. The gates' sandbox worker inherited no `USER`,
so `claude -p` answered `Not logged in` there from the day ADR 0094 moved node
bodies into a worker until this branch. Nothing in 0112 is wrong; it simply
never said which processes it covered, and the answer was "not the important
one". It is now: the login reaches the worker when, and only when, the repo
sets `gates.live_model_calls: true`, and the ledger records every pass where
it did.
