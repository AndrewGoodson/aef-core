# ADR 0069: The seams between CLI commands

## Status
Accepted. Phase B — running the loop end to end for the first time as one
sequence. Three defects, all in joins between individually-correct commands.

## Context
Every command was tested and green. The sequence
`aef run --record-runs → aef loop harvest → aef loop cycle → status → digest`
had **never been executed as one sequence**, and three of its four joins were
broken. This is the third time a defect has lived in a seam (ADR 0063, ADR
0065), which is now a pattern rather than a coincidence: component tests
cannot see how components are wired together.

## Defect 1 — the cycle's memory store was constructed empty

`cmd_cycle` built `InMemoryMemoryStore()` inline. That store is discarded
when the process exits, so the evidence the proposer reads was **empty on
every invocation**, and the reflection→proposer wire (ADR 0065) could never
fire from the CLI. Running the real command printed *"no admissible failure
memory: no candidate this cycle"* — and always would have.

`FileMemoryStore` (JSONL, append-only) makes records durable across
processes, which is the minimum a loop that claims to learn across runs needs.
`aef loop cycle --memory <path>` points at it. A malformed line raises rather
than being skipped: a memory file that silently drops records gives the
proposer less evidence than it thinks it has.

## Defect 2 — harvest bypassed the kill switch

`aef loop harvest` took no `--state`, so it never looked at the kill switch.
Harvest **writes to `corpus/`, which is the evidence every behavioural gate
is measured against** — so a halted loop could still have its gate evidence
changed underneath it. Now behind the same check as everything else that
mutates state.

`status` and `digest` remain deliberately readable while halted: reading why
the loop stopped is what you do when it stops. A test pins that asymmetry.

## Defect 3 — G1's defaults assumed this repository's layout

`DEFAULT_BUILD_COMMANDS` was `mypy --strict aef` plus `pytest -q` — aef-core's
own green bar. It runs against the **adopting** repo, which has no `aef/`
directory, so **G1 rejected every candidate in every adopting repo, forever**,
and silently, because the failure reads as an ordinary gate rejection.

The default is now `pytest -q` alone, and `--build-command` (repeatable)
takes the repo's real green bar. `LOOP.md` says so.

## What running it also surfaced

- **An edge to a reflect node does not wire it.** Routing is chosen by node
  code, not authorised by edges — so adding `Edge(work → reflect)` while
  `work` returns `END` means reflect never runs, and nothing complains. This
  is the ADR 0047 property working as designed, and it is an easy trap because
  adding an edge *looks* like wiring.
- **A fourth adopter obligation was undocumented**: G5 refuses every candidate
  until an owner-blessed baseline is archived. `LOOP.md` listed three
  obligations; it now lists four.
- Harvest correctly rejected two runs as non-reproducing when the recording
  graph differed from the harvesting graph. Working as designed.

## Consequences
- 13 tests, mostly source-level assertions on how commands are wired.
  Source assertions are usually a smell; here the property *is* the wiring,
  and no behavioural test of either component can see it.
- The full sequence now runs end to end: ledger verified, candidate proposed
  **citing real recorded memory**, local branch created and never pushed,
  gates G0/G1/G4 passing and G5 refusing for want of a baseline — the correct
  refusal, with the correct reason.

## Confidence
High on all three defects and their fixes, each reproduced by running the
real commands. **Not claimed:** that the remaining seams are sound. Three of
four joins in one sequence were broken; the other sequences
(`gate → monitor → rollback`, `adopt → record → harvest`) have had one
smoke-level pass at most.
