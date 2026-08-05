# ADR 0084: The six things that were written down and left

## Status
Accepted. Phase 2 item 2e — the items ADR 0074, 0079 and 0080 recorded as
findings and did not fix.

Recording a defect is not fixing it. Each of these sat in an ADR, true and
unaddressed, which is a slower version of not having found it.

## 1. `extends` resolved nothing, and said nothing

`AgentConfig.extends` defaults to `"_base"` and **nothing resolves a base
config** — not a missing one, and not a present one either. A planted base
supplying `objectives` still produced `objectives: Field required` in the
child.

The field accepted any string, so `extends: production-base` loaded clean and
inherited nothing. An owner could believe a shared policy applied when no code
had ever read the field.

Rejecting a non-default value is the smallest honest answer until inheritance
exists. Implementing inheritance is Phase 2 config work and a larger decision
than this ADR should make; loading clean while doing nothing is not a
defensible middle.

## 2. `aef trace` printed nothing on the scaffolded agent

The kernel never appends `Provenance` — it arrives only from a `StateDelta` —
and `aef init`'s template emitted none. So the documented
*execute → score → replay* demo replayed empty and scored `cost_tokens=0`,
which reads as a broken tool rather than an agent that reported nothing. The
scaffold now emits one.

## 3. `bless` and the gate could describe different trees

`bless` took an `agent_root`; `aef.cli.loop._config` never set a
`zone_policy`. With a non-default root, G5's baseline and candidate sides
would have read two different trees — the ADR 0074 defect, latent behind a
default nobody had changed yet. One `--agent-root` flag now feeds both, and
its help text says why they must agree.

## 4. A CRLF line came back as LF

`rewrite_constant` emitted a hardcoded `"\n"`, so rewriting one line of a
CRLF file left a single mixed ending. Small, and it means the proposal was
not the pure single-value edit its rationale described — the artefact G0
scanned differed from the change that was reasoned about, which is the same
class of problem as ADR 0078's working-tree laundering, three orders of
magnitude smaller.

## 5. Negative constants were unreachable through a dead regex branch

`_CONSTANT_RE` allowed `-?\d+`. `find_constants` filtered on
`ast.Constant`, and `X = -2` parses as `UnaryOp(USub, Constant)` — so the
regex's negative branch could never match anything the AST had returned. An
agent whose tunable was negative had nothing the proposer could reach, and
the regex claimed otherwise.

## 6. Two open merges rolled back to the wrong place

`archive.rollback(v)` **appends** v's content as a new version. The monitor
iterated merges in ledger order, so each rollback undid the previous one.
Reproduced:

```
after reverting v2: tree=b"MARKER='baseline'\n"
after reverting v3: tree=b"MARKER='regress-A'\n"   <- the first regression, back
```

Both were reported as rolled back. The ledger's `ROLLED_BACK` entries assert
a restore to the very change being reverted.

Reverting newest-first unwinds the stack in the order it was built. This is
ADR 0072's defect surviving in the n>1 case, and it is reachable only with
Tier-1 enabled — which is off, and which is the only state in which the
rollback machinery matters at all. A control that is only exercised when it
matters is worth being right before then.

## Confidence
High: each was reproduced by running before the fix and re-run after. **Not
claimed:** that items 1 and 2 are *solved*. Config inheritance still does not
exist — it now refuses instead of pretending — and the scaffold emits a
provenance record with `token_cost=0`, which makes `aef trace` non-empty
without making it informative. Both are honest states, not finished ones.
