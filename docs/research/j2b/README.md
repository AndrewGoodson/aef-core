# J2b — does a stepping stone produce a better descendant? (ADR 0198)

The measurement ADR 0160 said it could not make, on a rig where a candidate is
sometimes kept. Everything here is committed so the table in ADR 0198 can be
re-derived without a clone, a gate run or a live call.

| file | what it is |
|---|---|
| `run_j2b.py` | the runner. `--probe` measures the rig's premise, `--dry-run` prints the plan and the call arithmetic, `--live --arm <arm> --proposer <p>` runs one arm, `--relineage` re-reads a finished arm's persisted archive, `--report` / `--verify` renders the tables from the JSONL |
| `results.jsonl` | one object per turn as it landed, one summary per invocation, and one `kind: "lineage"` re-read per arm. Raw; nothing here was edited after the fact |
| `report.txt` | the two tables ADR 0198 publishes, as `--verify` prints them |
| `staircase.txt` | the rig's premise, measured: what the task metric does as `RETRY_BUDGET` and `QUALITY_THRESHOLD` move |
| `dry-run.txt` | the plan and the per-turn call arithmetic, printed before any call was made |
| `preflight.json` | the quota preflight, raw, on the exact argv `ClaudeCodeProvider` builds (ADR 0150) |
| `lineage-llm-greedy.txt` | `aef loop lineage list` on the greedy arm — a star: eight children, one parent |
| `lineage-llm-sampling.txt` | the same on the sampling arm — a tree three generations deep, every branch off a rejection, none of it kept |

## Re-running it

```bash
python docs/research/j2b/run_j2b.py --verify          # the tables, from the JSONL, 0 calls
make measure                                          # the same, diffed against ADR 0198
python docs/research/j2b/run_j2b.py --probe --workroot /tmp/j2b   # the staircase, 0 calls
```

The arms themselves need a scratch root outside the repository and, for the
`llm` proposer, one live call per turn:

```bash
python docs/research/j2b/run_j2b.py --live --arm greedy   --proposer rule_based --workroot /tmp/j2b
python docs/research/j2b/run_j2b.py --live --arm sampling --proposer llm --turns 4 --workroot /tmp/j2b
python docs/research/j2b/run_j2b.py --live --arm sampling --proposer llm --resume --turns 4 --workroot /tmp/j2b
python docs/research/j2b/run_j2b.py --relineage --workroot /tmp/j2b
```

Each arm clones this repository into its own scratch directory and reduces the
corpus to `demo_agent` — a measurement that left candidate branches behind in
the tree it was run from would be a measurement that changed its own subject.
`ClaudeCodeProvider.complete` is wrapped with a counter and a hard cap that
raises rather than spend past it, so `--max-calls 0` is how the rule-based arms
prove they were free.
