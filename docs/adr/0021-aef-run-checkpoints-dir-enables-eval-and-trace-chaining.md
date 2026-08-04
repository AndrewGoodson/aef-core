# ADR 0021: `aef run --checkpoints-dir` — before this, `aef run` could never be chained into `aef eval`/`aef trace`

## Status
Accepted

## Context
End-to-end chaining (run the CLI commands in the sequence a user actually
would, not just unit-test each in isolation — the technique that already
caught ADR 0018) surfaced the most consequential gap found tonight:
`aef run` always used `InMemoryDurabilityBackend`. That backend's data
lives only in the Python process's memory and is discarded the instant
the process exits. `aef eval`/`aef trace` both require a
`--checkpoints-dir` pointing at a `FileDurabilityBackend` directory.
Reproduced directly: `aef run smoke_graph --objective "test" ; aef eval
--checkpoints-dir ./checkpoints --run-id <the printed run_id>` fails with
"no checkpoints found" every single time, because `aef run` never wrote
anything to `./checkpoints` (or anywhere on disk) in the first place. This
made the three commands look like a workflow — run something, then
evaluate it, then inspect its trace — while actually being three
disconnected commands with no way to hand data from the first to the
other two.

For a scaffold whose whole stated purpose is supporting evaluation-gated,
observable agent loops (report §8/§10), a CLI where "run, then evaluate
what you just ran" doesn't work is a significant gap — arguably the most
user-facing one found tonight, on par with ADR 0018 (`aef init`'s own
output not being runnable).

## Decision
`run_graph_module` gained an optional `checkpoints_dir` parameter (CLI:
`aef run --checkpoints-dir PATH`). When given, it wires
`FileDurabilityBackend(Path(checkpoints_dir))` instead of
`InMemoryDurabilityBackend()`; when omitted, behavior is unchanged (a
quick one-off run, nothing persisted, verified to still write zero files).
This is the minimum change that makes `aef run --checkpoints-dir X`
followed by `aef eval --checkpoints-dir X --run-id <id>` and `aef trace
--checkpoints-dir X --run-id <id>` an actually-working sequence — verified
by running exactly that sequence against the real installed `aef`
console script in a scratch directory before writing any test.

`memory`/`tracer` stay in-memory-only regardless — this ADR only closes
the durability half of the gap, since that's the half `eval`/`trace`
specifically depend on.

## Consequences
- The three-command loop (`run` → `eval` → `trace`) this scaffold's CLI
  implies now genuinely works, not just in isolated unit tests but via
  the real console script.
- `aef run`'s default behavior (no `--checkpoints-dir`) is explicitly
  unchanged and now has a regression test proving it writes nothing —
  someone using `aef run` for a quick check doesn't pay a persistence
  cost they didn't ask for.
- `checkpoints_dir` uses the same `FileDurabilityBackend` real backend
  already built and tested in Phase 0/1 (ADR 0002) — no new durability
  mechanism, just finally wiring the existing one into the one CLI command
  that hadn't used it.

## Alternatives Considered
- **Make `FileDurabilityBackend` the default for `aef run`, always.**
  Rejected: would silently start writing files to disk for every quick
  `aef run` invocation, including ones just checking whether a graph
  compiles/runs at all — an unwanted side effect for the common case.
  Opt-in via an explicit flag matches how `--config` (ADR 0014) already
  works for this same command.
- **Have `aef eval`/`aef trace` accept an in-memory state directly
  (e.g., piped JSON) instead of requiring a shared directory.** Rejected
  as a larger redesign for less benefit: the checkpoints-directory model
  already exists, is tested, and matches how a real durable deployment
  would work (a shared, inspectable checkpoint store) — better to wire
  the existing mechanism through than invent a parallel one.

## Confidence
High — reproduced the exact failure with the real console script before
writing any fix, verified the fix resolves it the same way (real `aef
run` → `aef eval` → `aef trace` sequence, not just unit tests), and
confirmed the no-flag default path is unchanged with a dedicated
regression test.
