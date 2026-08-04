# Golden corpus

Recorded runs of the Zone A agent (`agents/demo/`). Every behavioural gate
stands on this, so how entries get in matters as much as what the gates do
with them.

## Splits — fixed at record time, never moved

| Split | Who sees it | Purpose |
|---|---|---|
| `train` | the proposer | the only evidence `grounded_in` may cite |
| `validation` | the gates | what G2/G3 score against |
| `holdout` | **the owner only** | the independent read of whether the loop improves anything |

Moving a file between split directories is **fatal** (ADR 0048): the file
records its own split and loading verifies it against the directory. A
scenario that could migrate would leak the holdout into the proposer's
evidence base, and G3's "beats the control cohort on held-out data" would
become a measurement of memorisation.

`aef loop record` writes to `train` by default and **refuses** to write to
`holdout` without `--i-am-spending-the-holdout`.

## Scenarios are recorded, never hand-written

A hand-written scenario encodes what someone *believed* the graph does; a
recorded one encodes what it did. The difference shows up exactly when they
diverge, which is the case a corpus exists to catch. `aef loop record` is the
only supported way in.

```
aef loop record agents.demo.graph --corpus corpus \
    --scenario-id my-case --objective "..." --split train
```

## The corpus never shrinks

`check_never_shrinks` fails if a previously-admitted scenario disappears —
a gate suite that can be made to pass by deleting the failing case is not a
suite. This runs from the base ref, so a candidate cannot retire its own
counterexample.

## What this seed corpus covers, and does not

Nine scenarios over `agents/demo`, deliberately spanning both sides of the
incumbent's capability: five that pass under the current constants and four
that do not. A corpus where everything already passes cannot demonstrate an
improvement; one where everything fails cannot demonstrate a regression.

**It does not cover:** model-backed nodes, tool calls, policy denials,
multi-node routing, or failure modes of any real workload. It exists to prove
the pipeline works end to end, not to gate a real agent. A repo adopting this
loop must record its own.
