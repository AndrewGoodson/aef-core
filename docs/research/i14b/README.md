# I14b — a fair test for the judge (ADR 0202)

ADR 0171 moved rubric dimension 3 on an AUC of 1.000 and said in its own
closing paragraph what that number was worth: *"perfect separation of ONE
failure family with n = 4: every negative is a word-cap overrun, so what has
been shown is that this judge detects that failure, not that it detects
failure."* `len(summary.split()) > cap` detects a word-cap overrun. This
directory is the set that a word count cannot grade, and the comparison re-run
on it.

| file | what it is |
|---|---|
| `prereg.txt` | written before the quota preflight: the design, the budget, and the three conditions that would move dimension 3 |
| `run_i14b.py` | the runner. `--build` derives the hard set from the corpus, `--dry-run` prints every case and the call arithmetic, `--live-grade`/`--live-choose`/`--guard-demo` spend, `--report` regenerates every table from the JSONL |
| `hardset.json` | the twelve cases: six matched pairs, the owner's label and a disputable sentence for each, the exact edit, the word count and the inherited-check verdict |
| `grades.jsonl` | 48 judgments (12 cases × 2 judges × 2 position-swapped samples), raw, one object per case as it landed |
| `choices.jsonl` | 24 pairwise choices plus the guard demonstration |
| `report.txt` | every table ADR 0202 publishes, as `--report` prints it |
| `dry-run.txt` | the plan, printed before anything was spent |
| `preflight.json`, `preflight-sonnet.json` | the two quota preflights, raw, on the exact argv `ClaudeCodeProvider` builds (ADR 0150) |

## The set, in one paragraph

Six passages from `corpus/`, each contributing the agent's own recorded
summary **verbatim** and that summary with **one minimal owner-authored edit**
that makes it wrong: a correct number with the wrong unit, the superseded
figure reported as the result, two entities swapped, a fabricated reason under
a right conclusion, the condition whose removal reverses the finding, and a
confident claim the passage explicitly withdraws. The judged state is the real
scenario's `reflect` `input_state` with `working_memory.summary` replaced and
nothing else touched.

**Every case is within its own word cap** — `--build` refuses to write the
file otherwise — so pass-everything, fail-everything and a word-count-only
judge all score exactly 6/12.

**The negatives are authored, not observed.** ADR 0171 recorded nineteen runs
against deliberately trappy passages to obtain content negatives and got none.
So this grades the judge; nothing here is a statement about how often the
agent fails.

## Re-running it

```bash
python docs/research/i14b/run_i14b.py --report      # every table, 0 calls
python docs/research/i14b/run_i14b.py --build       # re-derive the set from the corpus
make measure-ci                                     # the same, diffed against ADR 0202
pytest tests/reasoning/test_i14b_hardset.py         # the set's fairness properties
```

75 live calls were spent in total: 2 preflights, 48 grading, 24 choosing, 1 to
show the self-ranking guard firing on this repo's own `model: ""` default.
