# J2c — a staircase the proposer can climb (ADR 0203)

ADR 0198 measured `stepping_stone_keeps = 0` with a denominator of 5 and named
the missing half: *"a rig in which a rejected candidate is on the path to a
kept one **and** the proposer can take the second step. This rig had the first
and not the second."* This is that rig.

| file | what it is |
|---|---|
| `staircase.txt` | the premise, MEASURED through `aef loop score` and published before any arm ran |
| `prereg.txt` | written after the probe and before the seeded arms: the statistic, the two sources of chance, and the falsification |
| `run_j2c.py` | the runner. `--record` builds the corpus by running the agent, `--probe` measures the staircase, `--arms` runs the seeded sweep, `--report`/`--verify` render the tables |
| `corpus/` | **this worker's OWN corpus copy** — nine `ladder_agent` scenarios. The repository's `corpus/` is another worker's this wave, and two measurement branches may not touch one corpus |
| `results.jsonl` | one object per turn as it landed and one summary per run, twenty runs, raw |
| `report.txt` | the tables ADR 0203 publishes |
| `dry-run.txt` | the plan and the call arithmetic — zero, and asserted |

## Why the demo fixture could not do this

`agents/demo`'s winning square needs BOTH constants raised coherently, because
the null cohort mutates one constant per member. But `find_constants` returns
constants in source order and `cycle` takes `proposals[0]`, so from any parent
whatsoever the rule-based proposal raises `RETRY_BUDGET` and never
`QUALITY_THRESHOLD`. The demo's ladder is on an axis the proposer cannot walk,
and no parent policy fixes that.

`agents/ladder` puts the ladder on the axis the proposer DOES walk, and pays
for it by making the target narrow instead of two-dimensional — which is what
keeps the null hypothesis able to reject.

## Re-running it

```bash
python docs/research/j2c/run_j2c.py --verify        # the tables, from the JSONL, 0 calls
make measure                                        # the same, diffed against ADR 0203
python docs/research/j2c/run_j2c.py --probe --workroot /tmp/j2c    # the staircase
python docs/research/j2c/run_j2c.py --arms --seeds 10 --workroot /tmp/j2c
```

`python` must be on `PATH` for the arms: G1's build command is `python -c
"import agents.ladder.graph as g; g.build_graph()"`, and without it every
candidate is rejected by G1 before any behavioural gate runs — which is
exactly what happened on the first sweep here, and is recorded in ADR 0203
because a whole arm reported `stepping_stone_keeps = 0` for a reason that had
nothing to do with the archive.

Each arm clones this repository into its own scratch directory and replaces
the clone's `corpus/` with the ladder corpus. `ClaudeCodeProvider.complete` is
wrapped with a counter whose cap is **0**, so the arms are asserted free
rather than believed free.
