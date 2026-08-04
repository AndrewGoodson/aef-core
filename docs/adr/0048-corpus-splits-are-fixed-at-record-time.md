# ADR 0048: Corpus splits are fixed at record time; routes are tagged

## Status
Accepted. Implements M2 of the self-rewiring roadmap.

## Context
G2 and G3 both stand on a corpus of recorded runs, and none existed:
`Context` had no serializer and `END` had no JSON form at all (gap G4,
`00-current-state.md`). Building the codec and the corpus forced four
decisions that a naive implementation gets wrong in ways that fail silently
rather than loudly.

## Decision

**1. `Route` is tagged, never bare.** `END` is a dedicated singleton type
specifically so it can never collide with a node id (`contracts.py`).
Serialising it as the string `"END"` would reintroduce that collision the
moment someone names a node `END` — and the symptom would be a silently
wrong route in a golden scenario, not an error. Every route encodes as
`{"kind": "end" | "node" | "fanout", ...}`.

**2. Serialisation is canonical.** Sorted keys, fixed separators, trailing
newline. Byte-stability is a requirement rather than a nicety: every gate
downstream compares serialised traces, so a codec emitting keys in dict
order would make all of them flake intermittently.

**3. A scenario's split lives inside the scenario, and loading verifies it
against the directory.** `train` is the only split a proposer may cite;
`validation` is what gates score against; `holdout` is the owner's. If a
file could be moved from `holdout/` into `train/`, the holdout would quietly
become citable evidence and G3's "beats the control cohort on held-out data"
would degrade into a measurement of memorisation. The directory is a claim;
the file is the record, and a mismatch is fatal.

**4. Changing a scenario's split counts as shrinkage.** `check_never_shrinks`
rejects a missing id *and* a moved one, because moving is deletion from one
split dressed as an addition to another. A suite that can be made to pass by
retiring the case that fails is not a suite.

**5. `fixed_clock` refuses to invent a timestamp.** Re-execution replays the
`Context.now` values the recording observed. When a candidate asks for one
more than was recorded, that means it executed **more steps than the
incumbent** — a real behavioural difference, which G2 must report. Handing
it a fresh `now` would bury that finding under a timestamp mismatch.

## Consequences
- Round-trip and determinism are tested against a real `GraphExecutor` run,
  not a hand-built trace: write → read → re-execute yields identical node
  sequences and final state, and two re-executions serialise byte-identically.
- The never-shrinks known-bad case is explicit — deleting a scenario raises
  `CorpusShrankError`. `CorpusShrankError` is its own type because this is
  the one failure that would let a candidate erase its own counterexample.
- 33 tests. The anti-leak test physically relocates a holdout file into
  `train/` and asserts the load fails.
- The corpus lives in Zone B and is read from the base ref (ADR 0047), so a
  candidate cannot retire a scenario or move it between splits.
- **Deferred to M4/M5:** the comparison policy itself. This milestone makes
  scenarios storable and re-executable; deciding what counts as a regression
  is G2's job, not the codec's.
- **Not implemented:** a recorder that promotes a live run into a scenario
  with automatic split assignment. Splits are supplied explicitly for now,
  which keeps the owner in control of what lands in `holdout`.

## Alternatives Considered
- **Encode `END` as `"END"` or `null`.** Rejected: `null` is
  indistinguishable from a missing field, and `"END"` recreates the exact
  node-id collision the sentinel type was introduced to prevent.
- **Derive the split from a hash of the scenario id.** Rejected: it looks
  stable but silently re-partitions the entire corpus the moment the split
  ratio or hash changes, moving scenarios out of `holdout` with no record
  that it happened.
- **Let re-execution use a live clock and ignore timestamps when
  comparing.** Rejected: it discards the "candidate took more steps" signal,
  which is one of the more informative behavioural differences available.
- **Store traces as one append-only log rather than a file per scenario.**
  Deferred: a file per scenario makes the never-shrinks check a set
  comparison over filenames and makes a deletion visible in a git diff.

## Confidence
High on the codec — round-trip, determinism, and byte-stability are
directly tested, including timezone preservation and the `is_fallback` flag
that ADR 0039 made load-bearing. High on the anti-leak property, which is
tested by performing the move. Medium on the corpus format's durability:
nothing yet exercises it at scale, and `format_version` is recorded but
**no migration path is implemented** — the first breaking format change
will need one, and that is a known gap rather than an oversight.
