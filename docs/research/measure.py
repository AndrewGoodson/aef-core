#!/usr/bin/env python
"""`make measure` — re-derive every published measurement table and diff it
against the ADR that publishes it (ADR 0196).

ADR 0188's second independent score gave dimension 5 nine points out of ten,
and named the missing one exactly: *"several headline numbers reach a reader as
docstring prose with the data one directory away and no re-runner (`make
measure`) that regenerates the tables in CI"*. ADR 0191 then withdrew S1c's
`+2` **because its seed no longer reproduced on the current tree** — a fact a
re-runner would have surfaced the day the corpus moved, rather than a night
later during a hunt.

This is that re-runner. For each measurement under `docs/research/*/` it:

1. runs the measurement's runner in its shared `--verify` mode — re-derive the
   published table from the **committed raw data**, print it, write nothing,
   and make **zero live calls**;
2. extracts each pinned row from the runner's stdout;
3. extracts the *same* row from the ADR that publishes it — the ADR is the
   expectation, not a constant in this file, so perturbing a number in the ADR
   is caught the same way as perturbing the data;
4. reports drift as `measurement / row: ADR says X, re-derived Y`.

**Known drift is annotated, never silenced.** A row in `KNOWN_DRIFT` still
prints as a drift and still fails a default `make measure`; what the note buys
is `--against-expectations`, the CI mode, which fails when the drift set
*changes* — a new drift, or a known one that healed and left a stale note
behind. `make measure` is red on this tree today, by design, and ADR 0196
records which rows and why.

Usage:

    python docs/research/measure.py                     # every measurement
    python docs/research/measure.py --fast              # the CI subset
    python docs/research/measure.py --only i12c-seed
    python docs/research/measure.py --against-expectations --fast
    python docs/research/measure.py --list
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


@dataclass(frozen=True)
class Row:
    """One published number, pinned on both sides."""

    name: str
    adr_re: str
    derived_re: str
    #: Set when this row is known not to reproduce. The value must name the ADR
    #: paragraph that explains why, so a note can never stand without a record.
    known_drift: str | None = None


@dataclass(frozen=True)
class Measurement:
    id: str
    title: str
    adr: str
    argv: tuple[str, ...]
    rows: tuple[Row, ...]
    #: "fast" runs in CI. "slow" re-executes graphs from cassettes and is left
    #: to `make measure`; the line is drawn at roughly ten seconds.
    speed: str = "fast"
    #: Set when the runner itself cannot run on this tree.
    known_failure: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# The registry. Every measurement directory under docs/research/ appears here
# or is named in NOT_REDERIVABLE below with the reason.
# --------------------------------------------------------------------------

ADR_0155 = "docs/adr/0155-a-caller-that-writes-state-nobody-reads.md"
ADR_0156 = "docs/adr/0156-the-live-noise-floor-and-a-regression-under-it.md"
ADR_0159 = "docs/adr/0159-the-judge-ab-is-an-artifact-now.md"
ADR_0160 = "docs/adr/0160-the-archive-is-real-and-has-not-yet-bought-anything.md"
ADR_0162 = "docs/adr/0162-the-two-signals-and-which-one-came-apart.md"
ADR_0163 = "docs/adr/0163-the-pilot-on-the-clone-and-the-path-that-was-never-open.md"
ADR_0175 = "docs/adr/0175-the-arms-were-real-this-time-and-the-layer-still-did-not-pay.md"
ADR_0180 = "docs/adr/0180-the-good-column-and-the-quotation.md"
ADR_0193 = "docs/adr/0193-the-arms-re-run-on-the-corpus-that-exists.md"
ADR_0184 = "docs/adr/0184-the-lesson-was-fresh-and-the-layer-paid.md"
ADR_0186 = "docs/adr/0186-one-model-across-the-corpus-and-what-it-cost.md"
ADR_0198 = (
    "docs/adr/0198-the-tree-grew-from-the-rejections-and-none-of-it-was-better.md"
)
ADR_0202 = "docs/adr/0202-the-judge-on-a-set-a-word-count-cannot-grade.md"
ADR_0203 = (
    "docs/adr/0203-the-stepping-stone-paid-once-the-ladder-was-on-the-proposers-axis.md"
)

_WM_DROP_RE = (
    r"before \['api_key', 'keep_me', 'token'\]  ->  after \['keep_me'\]  \(count=(\d+)\)"
)

MEASUREMENTS: tuple[Measurement, ...] = (
    Measurement(
        id="i12-arms",
        title="I12 — the four arms on the wired graph",
        adr=ADR_0155,
        argv=("docs/research/i12/aggregate.py", "--verify"),
        rows=(
            Row(
                "(a) no retrieve, mean",
                r"\| \(a\) no retrieve \| \*\*([0-9.]+)\*\*",
                r"^\s+a\s+([0-9.]+)",
            ),
            Row(
                "(b) raw records, mean",
                r"\| \(b\) raw records \| \*\*([0-9.]+)\*\*",
                r"^\s+b\s+([0-9.]+)",
            ),
            Row(
                "(c) + knowledge, mean",
                r"\| \(c\) \+ knowledge \| \*\*([0-9.]+)\*\*",
                r"^\s+c\s+([0-9.]+)",
            ),
            Row(
                "(d) + LLM reflection, mean",
                r"\| \(d\) \+ LLM reflection \| \*\*([0-9.]+)\*\*",
                r"^\s+d\s+([0-9.]+)",
            ),
            Row(
                "largest within-arm spread",
                r"\*\*Largest within-arm spread: ([0-9.]+)\*\*",
                r"max within-arm spread \(the noise floor this rig can see\): ([0-9.]+)",
            ),
            Row(
                "total live calls", r"^(\d+) live calls, `--repeats 2`", r"total live calls: (\d+)"
            ),
        ),
        notes=(
            "The runner raised FileNotFoundError on every invocation until this "
            "increment: `HERE` pointed at a `results/` subdirectory the raw JSON "
            "was flattened out of. ADR 0155's table had no working re-runner.",
        ),
    ),
    Measurement(
        id="i12b-arms",
        title="S1b — the four arms, ADR 0175's tables",
        adr=ADR_0175,
        argv=("docs/research/i12b/aggregate.py", "--verify"),
        rows=(
            Row(
                "(a) no retrieve, mean",
                r"\| \(a\) no retrieve \| \*\*([0-9.]+)\*\*",
                r"\| \(a\) no retrieve \| \*\*([0-9.]+)\*\*",
            ),
            Row(
                "(b) raw records, mean",
                r"\| \(b\) raw records \| \*\*([0-9.]+)\*\*",
                r"\| \(b\) raw records \| \*\*([0-9.]+)\*\*",
            ),
            Row(
                "(c) + knowledge, mean",
                r"\| \(c\) \+ knowledge @ boost 3\.0 \| \*\*([0-9.]+)\*\*",
                r"\| \(c\) \+ knowledge @ boost 3\.0 \| \*\*([0-9.]+)\*\*",
            ),
            Row(
                "(d) + LLM reflection, mean",
                r"\| \(d\) \+ LLM reflection \| \*\*([0-9.]+)\*\*",
                r"\| \(d\) \+ LLM reflection \| \*\*([0-9.]+)\*\*",
            ),
            Row(
                "delta (b) − (a), mean",
                r"\| \(b\) − \(a\) — retrieval vs none \| \*\*([+\-0-9.]+)\*\*",
                r"\| \(b\) − \(a\) \| \*\*([+\-0-9.]+)\*\*",
            ),
            Row(
                "delta (d) − (c), mean",
                r"\| \(d\) − \(c\) — LLM reflection vs rule-based \| \*\*([+\-0-9.]+)\*\*",
                r"\| \(d\) − \(c\) \| \*\*([+\-0-9.]+)\*\*",
            ),
        ),
    ),
    Measurement(
        id="i12b-seed",
        title="S1b step 0 — the seed ADR 0175's arms started from",
        adr=ADR_0175,
        argv=("docs/research/i12b/seed.py", "--verify"),
        rows=(
            Row(
                "failure records",
                r"memory: (\d+) failure record\(s\)",
                r"memory: (\d+) failure record\(s\)",
            ),
        ),
        speed="slow",
        known_failure=(
            "imports `write_check_failure_record`, which ADR 0180 removed in "
            "favour of `record_check_outcomes`. ADR 0175's step-0 table has no "
            "runner that executes on this tree at all."
        ),
    ),
    Measurement(
        id="i12c-seed",
        title="S1c step 0 — the seed ADR 0184's +2 rests on",
        adr=ADR_0184,
        argv=("docs/research/i12c/seed.py", "--verify"),
        rows=(
            Row(
                "train scenarios",
                r"train scenarios: (\d+)   live calls",
                r"train scenarios: (\d+)   live calls",
            ),
            Row(
                "failure records",
                r"memory: (\d+) failure record\(s\)",
                r"memory: (\d+) failure record\(s\)",
                known_drift=(
                    "ADR 0191 F3 / ADR 0186 — the corpus moved to one model, so a "
                    "different set of train scenarios breaks the word cap. S1c's "
                    "+2 is withdrawn."
                ),
            ),
            Row(
                "records the excerpt property covers",
                r"any of the (\d+) record\(s\) derived from it",
                r"any of the (\d+) record\(s\) derived from it",
                known_drift="ADR 0191 F3 — follows the failure-record count above.",
            ),
            Row(
                "entry recurrence (distinct runs)",
                r"max_words  kind=failure runs=(\d+)",
                r"max_words  kind=failure runs=(\d+)",
                known_drift="ADR 0191 F3 — the consolidated entry now recurs over 7 runs, not 3.",
            ),
            Row(
                "consolidated entries",
                r"CONSOLIDATED: (\d+) knowledge entr",
                r"CONSOLIDATED: (\d+) knowledge entr",
            ),
        ),
        speed="slow",
    ),
    Measurement(
        id="i12d-arms",
        title="N2 — the four arms on the one-model corpus, ADR 0193's table",
        adr=ADR_0193,
        argv=("docs/research/i12d/aggregate.py", "--verify"),
        rows=(
            Row(
                "(b) raw records, repeat 0",
                r"\| \(b\) raw records \| 0 \| – \| ([0-9.]+)",
                r"\| \(b\) raw records \| 0 \| 0\.0 \| ([0-9.]+)",
            ),
            Row(
                "(c) + knowledge, repeat 1",
                r"\| \(c\) \+ knowledge \| 1 \| 8\.0 \| ([0-9.]+)",
                r"\| \(c\) \+ knowledge @ boost 8\.0 \| 1 \| 8\.0 \| ([0-9.]+)",
            ),
            Row(
                "(c) − (b) on the mean",
                r"\(c\) − \(b\) = \*\*\+?([0-9.]+)\*\* on the mean",
                r"\(c\) − \(b\) on the mean\s+= \+?([0-9.]+)",
            ),
        ),
        notes=(
            "Registered by the orchestrator after the merge: N2 and N5 were "
            "written blind to each other, and N2's aggregator took argv[1] as a "
            "results directory, so the driver's `--verify` became a path and the "
            "load came back empty (`KeyError: 'a'`). The re-runner caught a "
            "measurement that could not re-derive itself one increment after it "
            "was built, which is the whole claim of ADR 0196.",
        ),
    ),
    Measurement(
        id="i12c-arms",
        title="S1c — the four arms with repeats, ADR 0184's tables",
        adr=ADR_0184,
        argv=("docs/research/i12c/aggregate.py", "--verify"),
        rows=(
            Row(
                "(b) raw records, mean of repeats",
                r"\| \(b\) raw records \| 3 \| \*\*([0-9.]+)\*\*",
                r"\| \(b\) raw records \| 3 \| \*\*([0-9.]+)\*\*",
            ),
            Row(
                "(b) repeat spread",
                r"\| \(b\) raw records \| 3 \| \*\*[0-9.]+\*\* \| \*\*([0-9.]+)\*\*",
                r"\| \(b\) raw records \| 3 \| \*\*[0-9.]+\*\* \| ([0-9.]+) \|",
            ),
            Row(
                "(c) + knowledge, mean of repeats",
                r"\| \(c\) \+ knowledge @ 3\.0 \| 2 \| \*\*([0-9.]+)\*\*",
                r"\| \(c\) \+ knowledge @ boost 3\.0 \| 2 \| \*\*([0-9.]+)\*\*",
            ),
            Row(
                "(c) − (b) on the mean",
                r"\(c\) − \(b\) on the mean       = ([+\-0-9.]+)",
                r"\(c\) − \(b\) on the mean       = ([+\-0-9.]+)",
            ),
            Row(
                "(c) − (b) on the negatives",
                r"\(c\) − \(b\) on the negatives  = ([+\-0-9.]+)",
                r"\(c\) − \(b\) on the negatives  = ([+\-0-9.]+)",
            ),
            Row("the pre-registered branch", r"    BRANCH: (.+)\n", r"    BRANCH: (.+)\n"),
        ),
        notes=(
            "The arm table re-derives exactly: it reads arms.jsonl, which is "
            "committed. It is the SEED underneath it (i12c-seed) that moved, "
            "which is why ADR 0191 withdrew the +2 rather than the table.",
        ),
    ),
    Measurement(
        id="i13-floor",
        title="I13 — the live noise floor and the regression under it",
        adr=ADR_0156,
        argv=("docs/research/i13/verify.py", "--verify"),
        rows=(
            Row(
                "floor, mean of means",
                r"\| floor, mean of means \| ([0-9.]+) \|",
                r"\| floor, mean of means \| ([0-9.]+) \|",
            ),
            Row(
                "regression, mean of means",
                r"\| regression, mean of means \| ([0-9.]+) \|",
                r"\| regression, mean of means \| ([0-9.]+) \|",
            ),
            Row(
                "the fall",
                r"\| \*\*fall\*\* \| \*\*([0-9.]+)\*\* \|",
                r"\| \*\*fall\*\* \| \*\*([0-9.]+)\*\* \|",
            ),
            Row(
                "floor spread",
                r"\| floor spread \(max − min\) \| ([0-9.]+) \|",
                r"\| floor spread \(max − min\) \| ([0-9.]+) \|",
            ),
            Row(
                "floor stdev of the means",
                r"\| floor stdev of the means \| ([0-9.]+) \|",
                r"\| floor stdev of the means \| ([0-9.]+) \|",
            ),
            Row(
                "fall ÷ floor stdev",
                r"\| fall ÷ floor stdev \| ([0-9.]+) \|",
                r"\| fall ÷ floor stdev \| ([0-9.]+) \|",
            ),
            Row(
                "floor repeat 3, sum-13",
                r"\| 3 \| 0\.6667 \| 0\.3764 \| 370 \| \*\*([0-9.]+)\*\*",
                r"\| 3 \| 0\.6667 \| 0\.3764 \| 370 \| ([0-9.]+)",
            ),
        ),
        notes=(
            "I13 committed six raw `aef loop score --json` payloads and then "
            "typed ADR 0156's three tables by hand. `verify.py` is the "
            "arithmetic that was missing; every number reproduces.",
        ),
    ),
    Measurement(
        id="i14-judges",
        title="I14 — the judge A/B (v1, ADR 0159)",
        adr=ADR_0159,
        argv=("docs/research/i14/run_i14.py", "--verify"),
        rows=(
            Row(
                "rule-based agrees with the owner checks",
                r"\| rule-based \(`RuleBasedJudge`, no model call\) \| \*\*(\d+)/18\*\*",
                r"rule-based agrees with the owner checks: (\d+)/18",
            ),
            Row(
                "LLM agrees with the owner checks",
                r"\| LLM \(`LLMJudge`, `working_memory` in evidence\) \| \*\*(\d+)/18\*\*",
                r"LLM        agrees with the owner checks: (\d+)/18",
            ),
            Row(
                "the two judges agree with each other",
                r"agree with \*\*each other on (\d+)/18\*\*",
                r"the two judges agree with each other:    (\d+)/18",
            ),
            Row(
                "oracle B pass rate",
                r"\*\*(\d+)/18 pass and has no negatives at all\*\*",
                r"oracle B \(contains made case-insensitive\): (\d+)/18 pass",
                known_drift=(
                    "ADR 0196 — oracle B is the one block `--report` recomputes live "
                    "from `corpus/`, and the corpus moved to one model (ADR 0186). "
                    "ADR 0186 disclosed the same drift for v2 and missed v1."
                ),
            ),
        ),
    ),
    Measurement(
        id="i14-judges-v2",
        title="I14 — the judge A/B (v2, restated by ADR 0186)",
        adr=ADR_0186,
        argv=(
            "docs/research/i14/run_i14.py",
            "--verify",
            "--out",
            "docs/research/i14/results-v2.jsonl",
        ),
        rows=(
            Row(
                "oracle B pass count on today's corpus",
                r"the split is \*\*(\d+) pass / \d+ fail\*\*",
                r"oracle B \(contains made case-insensitive\): (\d+)/17 pass",
            ),
        ),
        notes=(
            "ADR 0186 §'What this changes' already declared `report-v2.txt` "
            "stale and published the corrected split. This row proves the "
            "correction, and it is why the committed report-v2.txt is not "
            "byte-compared here.",
        ),
    ),
    Measurement(
        id="j2-archive",
        title="J2/S4 — greedy vs sampling over the archive",
        adr=ADR_0160,
        argv=("docs/research/j2/run_j2.py", "--verify"),
        rows=(
            Row(
                "greedy: distinct parents",
                r"\| greedy \| 8 \| 0 \| 8 \| \*\*(\d+)\*\*",
                r"\| greedy \| 8 \| 0 \| 8 \| (\d+) \|",
            ),
            Row(
                "sampling: distinct parents",
                r"\| sampling \| 7 \| 0 \| 7 \| \*\*(\d+)\*\*",
                r"\| sampling \| 7 \| 0 \| 7 \| (\d+) \|",
            ),
            Row(
                "greedy: turns",
                r"\| greedy \| (\d+) \| 0 \| 8 \|",
                r"\| greedy \| (\d+) \| 0 \| 8 \|",
            ),
        ),
    ),
    Measurement(
        id="j4-selfpref",
        title="J4 — judge self-preference",
        adr=ADR_0162,
        argv=("docs/research/j4/run_j4_selfpref.py", "--verify"),
        rows=(
            Row(
                "P(prefers A), judge opus",
                r"\| `claude-opus-5\[1m\]` \| yes \(A\) \| \*\*([0-9.]+)\*\* "
                r"\(5 of 7 consistent pairs\)",
                r"judge opus    ([0-9.]+)",
            ),
            Row(
                "P(prefers A), judge haiku",
                r"\| `claude-haiku-4-5-20251001` \| yes \(B\) \| ([0-9.]+) \(4 of 9\)",
                r"judge haiku   ([0-9.]+)",
            ),
        ),
    ),
    Measurement(
        id="j4-harm",
        title="J4 — does the lesson harm the runs it did not come from",
        adr=ADR_0162,
        argv=("docs/research/j4/run_j4_harm.py", "--verify"),
        rows=(
            Row(
                "sum-23-cransley-cut, baseline words",
                r"\| `sum-23-cransley-cut` \| 25 \| (\d+) w, 5/5 \|",
                r"^sum-23-cransley-cut\s+25\s+(\d+)\s",
            ),
            Row(
                "sum-23-cransley-cut, with-lesson words",
                r"\| `sum-23-cransley-cut` \| 25 \| 23 w, 5/5 \| \*\*(\d+) w\*\*",
                r"^sum-23-cransley-cut\s+25\s+23\s+(\d+)(?=\d/\d)",
            ),
            Row(
                "sum-39-coldbeck-society, with-lesson words",
                r"\| `sum-39-coldbeck-society` \| 38 \| 38 w, 5/5 \| \*\*(\d+) w\*\*",
                r"^sum-39-coldbeck-society\s+38\s+38\s+(\d+)(?=\d/\d)",
            ),
        ),
    ),
    Measurement(
        id="j4-tally",
        title="J4 — the helpful/harmful tally, as ADR 0180 corrected it",
        adr=ADR_0180,
        argv=("docs/research/j4/run_j4_harm.py", "--tally"),
        rows=(
            Row(
                "helpful, after ADR 0180's `_tally` correction",
                r"max_words  x10  helpful=(\d+) harmful=3 harmful_elsewhere=1",
                r"max_words\s+x10  helpful=(\d+) harmful=3",
            ),
            Row(
                "harmful",
                r"max_words  x10  helpful=\d+ harmful=(\d+) harmful_elsewhere=1",
                r"max_words\s+x10  helpful=\d+ harmful=(\d+)",
            ),
        ),
        notes=(
            "`docs/research/j4/report-tally.txt` still reads `helpful=7`: it is "
            "the artefact from BEFORE ADR 0180 corrected `_tally`, and was never "
            "regenerated. The ADR is right and the committed .txt is stale — "
            "which is the exact failure mode a re-runner exists to make visible.",
        ),
    ),
    Measurement(
        id="pilot-marlin-control",
        title="M6 — the redaction control ADR 0119 demands",
        adr=ADR_0163,
        argv=("docs/research/pilot-marlin/scan_control.py", "--verify"),
        rows=(
            Row(
                "email planted",
                r"^email           substitutions=(\d+)",
                r"^  email\s+substitutions=(\d+)",
            ),
            Row(
                "api_key planted",
                r"^api_key         substitutions=(\d+)",
                r"^  api_key\s+substitutions=(\d+)",
            ),
            Row(
                "bearer planted",
                r"^bearer          substitutions=(\d+)",
                r"^  bearer\s+substitutions=(\d+)",
            ),
            Row(
                "aws_key planted",
                r"^aws_key         substitutions=(\d+)",
                r"^  aws_key\s+substitutions=(\d+)",
            ),
            Row(
                "opaque_secret planted",
                r"^opaque_secret   substitutions=(\d+)",
                r"^  opaque_secret\s+substitutions=(\d+)",
            ),
            Row(
                "working-memory keys dropped",
                _WM_DROP_RE,
                _WM_DROP_RE,
            ),
            # Pinned against ADR 0163's 2026-09-05 erratum, not against its
            # original §5: the residual is closed in the code (ADR 0197) and
            # the committed `06-redaction-control.txt` still shows the old 0.
            # The ADR carries both, in order, which is what a record is for.
            Row(
                "marlin's own subscription UUID (0163 erratum)",
                r"> marlin's own subscription UUID: substitutions=(\d+)",
                r"^  uuid\s+substitutions=(\d+)",
            ),
        ),
    ),
    Measurement(
        id="j2b-archive",
        title="N8 — does a stepping stone produce a better descendant?",
        adr=ADR_0198,
        argv=("docs/research/j2b/run_j2b.py", "--verify"),
        rows=(
            # The statistic the increment exists for, pinned in BOTH arms of
            # the proposer that kept something. A regression that made a
            # rejected member look kept would move these off 0, which is the
            # direction that would matter.
            Row(
                "llm/greedy: kept from a rejected member",
                r"\| llm \| greedy \| 8 \| 1 \| 7 \| 2 \| 0 \| \*\*(\d+)\*\*",
                r"\| llm \| greedy \| 8 \| 1 \| 7 \| 2 \| 0 \| 0 \| \*\*(\d+)\*\*",
            ),
            Row(
                "llm/sampling: kept from a rejected member",
                r"\| llm \| sampling \| 8 \| 1 \| 7 \| 6 \| 5 \| \*\*(\d+)\*\*",
                r"\| llm \| sampling \| 8 \| 1 \| 7 \| 6 \| 0 \| 5 \| \*\*(\d+)\*\*",
            ),
            # And the DENOMINATOR, which is what makes the 0 above readable:
            # sampling built on a rejection five times and greedy never did.
            Row(
                "llm/sampling: candidates from a rejected member",
                r"\| llm \| sampling \| 8 \| 1 \| 7 \| 6 \| (\d+) \|",
                r"\| llm \| sampling \| 8 \| 1 \| 7 \| 6 \| 0 \| (\d+) \|",
            ),
            Row(
                "llm/sampling: distinct parents",
                r"\| llm \| sampling \| 8 \| 1 \| 7 \| (\d+) \|",
                r"\| llm \| sampling \| 8 \| 1 \| 7 \| (\d+) \|",
            ),
            Row(
                "llm/greedy: distinct parents",
                r"\| llm \| greedy \| 8 \| 1 \| 7 \| (\d+) \|",
                r"\| llm \| greedy \| 8 \| 1 \| 7 \| (\d+) \|",
            ),
            Row(
                "rule_based/sampling: turns before the repeated-tree stop",
                r"\| rule_based \| sampling \| (\d+) \| 0 \| 3 \|",
                r"\| rule_based \| sampling \| (\d+) \| 0 \| 3 \|",
            ),
        ),
    ),
    Measurement(
        id="i14b-hardset",
        title="P3 — the judge on a set a word count cannot grade",
        adr=ADR_0202,
        argv=("docs/research/i14b/run_i14b.py", "--report"),
        rows=(
            # The three statistics the rubric point rests on, all of the arm
            # the repo actually ships. ADR 0159's lesson is that any ONE of
            # them can be a constant function in disguise, so all three are
            # pinned and a regression that flattened the judge would move at
            # least two.
            Row(
                "llm-opus: agreement with the owner's labels",
                r"\| `llm-opus` \(session default\) \| \*\*(\d+)\*\*/12",
                r"llm-opus\s+(\d+)/12",
            ),
            Row(
                "llm-opus: AUC over the 36 pass/fail pairs",
                r"\| `llm-opus` \(session default\) \| \*\*12\*\*/12 \| \*\*([0-9.]+)\*\*",
                r"llm-opus\s+12/12\s+([0-9.]+)",
            ),
            Row(
                "llm-opus: matched pairs scored the right way round",
                r"\| \*\*12\*\*/12 \| \*\*1\.000\*\* \| \*\*(\d+)\*\*/6",
                r"llm-opus\s+12/12\s+1\.000\s+(\d+)/6",
            ),
            Row(
                "llm-opus: max position delta",
                r"\| \*\*12\*\*/12 \| \*\*1\.000\*\* \| \*\*6\*\*/6 \| \*\*([0-9.]+)\*\*",
                r"llm-opus\s+12/12\s+1\.000\s+6/6\s+([0-9.]+)",
            ),
            Row(
                "llm-sonnet: agreement (the disinterested judge)",
                r"\| `llm-sonnet` \(disinterested\) \| \*\*(\d+)\*\*/12",
                r"llm-sonnet\s+(\d+)/12",
            ),
            # And the baselines, because the judge's number means nothing
            # without them. A change that made the set unbalanced, or let a
            # word counter discriminate, moves these before it moves the arms.
            Row(
                "baseline: answer 'pass' to everything",
                r'\| answer "pass" to everything \| \*\*(\d+)\*\*/12',
                r"answer 'pass' to everything\s+(\d+)/12",
            ),
            Row(
                "baseline: word count against the cap only",
                r"\| word count against the cap only \| \*\*(\d+)\*\*/12",
                r"word count against the cap only\s+(\d+)/12",
            ),
            Row(
                "baseline: the corpus's own inherited regex checks",
                r"inherited regex checks \| \*\*(\d+)\*\*/12",
                r"the corpus's own inherited checks\s+(\d+)/12",
            ),
        ),
    ),
    Measurement(
        id="j2c-staircase",
        title="P4 — a staircase the proposer can climb",
        adr=ADR_0203,
        argv=("docs/research/j2c/run_j2c.py", "--verify"),
        rows=(
            # THE statistic, in both arms. ADR 0198 pinned the same one at 0;
            # a regression that made a rejected member read as kept, or that
            # stopped the sampler reaching one, moves these.
            Row(
                "greedy: kept from a rejected member",
                r"\| greedy \| 10 \| 0 \| 0 \| \*\*(\d+)\*\*",
                r"greedy\s+10\s+0\s+0\s+\*\*(\d+)\*\*",
            ),
            Row(
                "sampling: kept from a rejected member",
                r"\| sampling \| 10 \| 8 \| 8 \| \*\*(\d+)\*\*",
                r"sampling\s+10\s+8\s+8\s+\*\*(\d+)\*\*",
            ),
            # The denominator and the rung, which are what make the number
            # above readable: 8 of 8 attempts, all at BATCH_SIZE 5.
            Row(
                "sampling: candidates from a rejected member",
                r"\| sampling \| 10 \| 8 \| (\d+) \|",
                r"sampling\s+10\s+8\s+(\d+)\s",
            ),
            Row(
                "sampling: runs that reached rung 5",
                r"\| sampling \| 10 \| 8 \| 8 \| \*\*8\*\* \| (\d+) \|",
                r"sampling\s+10\s+8\s+8\s+\*\*8\*\*\s+(\d+)\s",
            ),
            Row(
                "greedy: runs that reached rung 5",
                r"\| greedy \| 10 \| 0 \| 0 \| \*\*0\*\* \| (\d+) \|",
                r"greedy\s+10\s+0\s+0\s+\*\*0\*\*\s+(\d+)\s",
            ),
        ),
    ),
)

#: Measurement directories with no offline re-derivation, and why. Named here
#: rather than omitted, because a measurement quietly absent from a re-runner
#: is the state ADR 0188 deducted for.
NOT_REDERIVABLE: tuple[tuple[str, str], ...] = (
    (
        "docs/research/pilot-marlin/scan_runs.py",
        "needs marlin's `.aef/runs`, which ADR 0163 deliberately does not commit "
        '("the scan\'s output is what is committed; no raw recorded run is"). '
        "Its planted-fault control IS re-derived, as pilot-marlin-control.",
    ),
    (
        "docs/research/pilot-marlin/repro_two_blockers.py",
        "reproduces two blockers against a marlin clone; no clone, no run.",
    ),
    (
        "docs/research/second-repo/",
        "transcripts of two adoption sessions, not a measurement with a table.",
    ),
    (
        "docs/research/i12/repro_regex_hang.py, i13/redos_repro.py",
        "timing reproductions of a ReDoS; wall-clock assertions, deliberately "
        "not pinned to a number in CI.",
    ),
    (
        "docs/research/i12b/boost_sweep.py, i12c/boost_sweep.py",
        "their published result (`results/boost_sweep.json`) is a ranking sweep "
        "that decides one knob; both are downstream of the same seed as "
        "i12c-seed and drift with it.",
    ),
)


# --------------------------------------------------------------------------
# The driver
# --------------------------------------------------------------------------


@dataclass
class RowResult:
    measurement: str
    row: str
    status: str  # ok | drift | missing-adr | missing-derived | xfail | stale-note
    published: str = ""
    derived: str = ""
    detail: str = ""

    @property
    def key(self) -> str:
        return f"{self.measurement}/{self.row}"


def _run(measurement: Measurement, root: Path) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    proc = subprocess.run(  # noqa: S603
        [PY, *measurement.argv],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _extract(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else None


def check(measurement: Measurement, root: Path) -> list[RowResult]:
    rc, out = _run(measurement, root)
    if rc != 0:
        tail = [ln for ln in out.strip().splitlines() if ln.strip()]
        detail = tail[-1] if tail else f"exit {rc}, no output"
        status = "xfail" if measurement.known_failure else "drift"
        return [
            RowResult(
                measurement.id,
                "<runner>",
                status,
                detail=f"runner exited {rc}: {detail}",
            )
        ]

    adr_text = (root / measurement.adr).read_text()
    results = []
    for row in measurement.rows:
        published = _extract(row.adr_re, adr_text)
        derived = _extract(row.derived_re, out)
        if published is None:
            results.append(
                RowResult(
                    measurement.id,
                    row.name,
                    "missing-adr",
                    detail=f"{measurement.adr} no longer publishes this row "
                    f"(pattern {row.adr_re!r} did not match) — it moved or was reworded",
                )
            )
            continue
        if derived is None:
            results.append(
                RowResult(
                    measurement.id,
                    row.name,
                    "missing-derived",
                    published=published,
                    detail=f"the runner's output has no {row.derived_re!r}",
                )
            )
            continue
        if published == derived:
            status = "stale-note" if row.known_drift else "ok"
            results.append(
                RowResult(
                    measurement.id,
                    row.name,
                    status,
                    published,
                    derived,
                    detail=""
                    if status == "ok"
                    else f"reproduces again — remove: {row.known_drift}",
                )
            )
        else:
            results.append(
                RowResult(
                    measurement.id,
                    row.name,
                    "xfail" if row.known_drift else "drift",
                    published,
                    derived,
                    detail=row.known_drift or "",
                )
            )
    return results


BAD = {"drift", "missing-adr", "missing-derived", "stale-note"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fast", action="store_true", help="the CI subset (no cassette replays)")
    parser.add_argument("--only", action="append", default=[], help="measurement id (repeatable)")
    parser.add_argument("--list", action="store_true", help="list the registry and exit")
    parser.add_argument(
        "--against-expectations",
        action="store_true",
        help="CI mode: fail only when the drift set CHANGES (a new drift, or a "
        "known drift that healed). A default run fails on any drift at all.",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    selected = [
        m
        for m in MEASUREMENTS
        if (not args.only or m.id in args.only) and (not args.fast or m.speed == "fast")
    ]

    if args.list:
        for m in MEASUREMENTS:
            print(f"{m.id:24} {m.speed:5} {m.adr.split('/')[-1][:8]}  {' '.join(m.argv)}")
        print()
        for path, why in NOT_REDERIVABLE:
            print(f"not re-derivable: {path}\n  {why}")
        return 0

    all_rows: list[RowResult] = []
    for m in selected:
        print(f"\n=== {m.id} — {m.title}")
        print(f"    ADR {m.adr}")
        print(f"    $ python {' '.join(m.argv)}")
        rows = check(m, args.root)
        all_rows.extend(rows)
        for r in rows:
            if r.status == "ok":
                print(f"    ok    {r.row:44} {r.derived}")
            elif r.status == "xfail":
                if r.row == "<runner>":
                    print(f"    XFAIL {r.row:44} {r.detail}")
                    print(f"          expected: {m.known_failure}")
                else:
                    print(
                        f"    XFAIL {r.row:44} ADR says {r.published!r}, re-derived {r.derived!r}"
                    )
                    print(f"          expected: {r.detail}")
            else:
                print(f"    DRIFT {r.row:44} ADR says {r.published!r}, re-derived {r.derived!r}")
                if r.detail:
                    print(f"          {r.detail}")
        for note in m.notes:
            print(f"    note: {note}")

    bad = [r for r in all_rows if r.status in BAD]
    xfail = [r for r in all_rows if r.status == "xfail"]
    ok = [r for r in all_rows if r.status == "ok"]

    print(f"\n{'-' * 76}")
    print(f"{len(ok)} row(s) reproduce, {len(xfail)} expected drift(s), {len(bad)} unexplained")

    expected_keys = {
        f"{m.id}/{row.name}" for m in selected for row in m.rows if row.known_drift
    } | {f"{m.id}/<runner>" for m in selected if m.known_failure}
    observed_keys = {r.key for r in xfail}

    if args.against_expectations:
        new = observed_keys - expected_keys
        healed = expected_keys - observed_keys
        for r in bad:
            print(
                f"NEW DRIFT   {r.key}: ADR says {r.published!r}, "
                f"re-derived {r.derived!r} {r.detail}"
            )
        for key in sorted(new):
            print(f"NEW DRIFT   {key}")
        for key in sorted(healed):
            print(f"HEALED      {key} — it reproduces again; remove its known_drift note")
        if bad or new or healed:
            return 1
        print("the drift set is exactly the one recorded in measure.py — no change")
        return 0

    for r in xfail:
        print(f"expected drift: {r.key} — {r.detail}")
    if bad or xfail:
        print(
            "\nFAILED. Each row above names the measurement, the row, and both "
            "numbers. Expected drift is still drift: a published number that no "
            "longer re-derives is a published number nobody should cite, whether "
            "or not an ADR explains it. `--against-expectations` is the CI mode "
            "and passes while the drift set is unchanged."
        )
        return 1
    print("every published row re-derives from committed data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
