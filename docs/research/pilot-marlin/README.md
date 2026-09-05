# M6 — the marlin pilot, raw artefacts (ADR 0163)

Every command of the pilot sequence and its real output, in order. The pilot ran
on a **copy** of the read-only clone at `<scratchpad>/pilot-marlin`, with its
`origin` remote (which pointed at `/Users/raptor/marlin`) removed before
anything executed. Nothing was pushed anywhere.

## What is committed, and what deliberately is not

**Committed:** the redaction scan's *output*, the objectives, and the **first
line** of each answer.

**Not committed:** any recorded run. `<runs>/<uuid>.json` holds the full trace
of a live model call and this directory is in git — which is precisely the
reason ADR 0119's redaction step exists. The scan that would have run inside
`harvest` is reproduced here as output rather than as its input.

The two scan scripts are committed so the numbers can be recomputed against the
same policy; they take a runs directory as `argv[1]` and read nothing else.

| file | what it is |
|---|---|
| `00-preflight.json` | the quota preflight, raw, on the exact argv `ClaudeCodeProvider` builds (ADR 0150) |
| `01-adopt.txt` | `aef adopt --dir .` on a repo adopted by an older `aef` |
| `02-migrate.txt` | `aef migrate --dir .` — 8 prompt-agent graphs, the containment block, the blast radius |
| `03-objectives-and-answers.txt` | the five real objectives and the first line of each answer, post-redaction |
| `04-harvest.txt` | `aef loop harvest`, with and without `--include-successes`: **0 promoted, 5 rejected** |
| `05-redaction-scan.txt` | ADR 0119's policy over all five runs: 0 substitutions, 0 output matches |
| `06-redaction-control.txt` | the control — 5 of 5 planted shapes caught, and the residual this repo's own UUID is |
| `07-two-blockers.txt` | the three-arm isolation of F-M6-1 and F-M6-2 |
| `08-bootstrap-1.txt`, `09-bootstrap-2.txt` | the path that did populate the corpus, and the two check-derived failure records |
| `10-bless.txt`, `11-doctor.txt` | the baseline and the six obligations |
| `12-cycle.txt`, `13-ledger.json` | one live cycle: proposal, every gate's verdict, `live_model_calls: true`, drift |
| `14-cycle-runs-noop.txt` | F-M6-3 — `cycle --runs` is silent without `--module`, two arms, one flag apart |
| `15-monitor.txt`, `16-digest.txt` | what the owner reads the next morning |
| `repro_two_blockers.py` | the reproduction, offline, zero live calls, `aef/` unmodified |
| `scan_runs.py`, `scan_control.py` | the redaction scan and its positive control |
