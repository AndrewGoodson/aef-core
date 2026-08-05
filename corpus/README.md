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

## A corpus with no tripwire cannot detect reward hacking

This is the sharpest thing to know about the corpus, and it is not
theoretical: a one-line change making the agent ignore its inputs and always
report success passed **all six gates** (ADR 0060). G2 checks outcome class
and G3 scores a function of that same class, so both ask the agent whether it
succeeded and record the answer.

The fix is ground truth you supply. Label at least one scenario
`must_fail` — a task genuinely **beyond** the agent's remit, where reporting
success is a lie rather than an improvement. A candidate that "passes" it
fails G2 as a security event.

Tripwires must be **impossible in principle, not merely hard**. Labelling a
difficult-but-achievable task `must_fail` rejects real progress as reward
hacking; that mistake was made first and caught by a test.

**Harvested scenarios never carry a label.** Only a human can say a task
should have failed — a `must_fail` the system set for itself is a tripwire it
set for itself.
