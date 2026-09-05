"""S1b — read the four arm JSONs and print every table ADR 0175 quotes.

The two subset columns are the point. This rig has no budget for repeats
(a/b/c/d cost 119 of the 130 live calls), so the noise bar is not taken from
repeating an arm — it is **measured inside the experiment**, from the scenarios
where two arms sent BYTE-IDENTICAL draft prompts:

- (c) and (d) sent identical prompts on **all 17** scenarios — arm (d)'s 51
  extra reflection calls never reached the drafting model — so every point of
  (d) − (c) is same-prompt live variance;
- (c) and (b) sent identical prompts on the **7** scenarios where the
  consolidated entry ranked outside `render_retrieved_context`'s top-5.

Usage:
  <venv>/bin/python aggregate.py [results-dir]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

NEGATIVES = (
    "sum-30-ganister-tarn",
    "sum-33-cotterdale-bus",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
)


def main() -> None:
    # `--verify` is the shared re-runner interface (ADR 0196): re-derive the
    # published table from the committed raw JSON, print it, write nothing,
    # zero live calls. That is what this script already did unconditionally,
    # so the flag is an affirmation rather than a mode; it exists so one
    # driver can invoke every runner the same way.
    argv = [a for a in sys.argv[1:] if a != "--verify"]
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent / "results"
    arms = {k: json.loads((root / f"{k}_r0.json").read_text()) for k in "abcd"}
    ids = list(arms["a"]["per_scenario"])

    print("| arm | mean | negatives (n=4) | rest (n=13) | calls | secs | draft-prompt sha256 |")
    print("|---|---|---|---|---|---|---|")
    label = {
        "a": "(a) no retrieve",
        "b": "(b) raw records",
        "c": "(c) + knowledge @ boost 3.0",
        "d": "(d) + LLM reflection",
    }
    for k, d in arms.items():
        print(
            f"| {label[k]} | **{d['mean']:.4f}** | {d['mean_negatives']:.4f} | "
            f"{d['mean_positives']:.4f} | {d['calls']} | {d['secs']:.0f} | "
            f"`{d['draft_prompt_sha256'][:16]}…` |"
        )

    print("\n| scenario | (a) | (b) | (c) | (d) | lesson in (c)'s prompt |")
    print("|---|---|---|---|---|---|")
    for i in ids:
        neg = " **NEG**" if i in NEGATIVES else ""
        row = " | ".join(f"{arms[k]['per_scenario'][i]:.2f}" for k in "abcd")
        print(f"| `{i}`{neg} | {row} | {'yes' if arms['c']['entry_in_prompt'][i] else 'no'} |")

    print("\n| comparison | delta (mean) | delta (negatives) |")
    print("|---|---|---|")
    for x, y in (("b", "a"), ("c", "b"), ("d", "c"), ("d", "b")):
        print(
            f"| ({x}) − ({y}) | **{arms[x]['mean'] - arms[y]['mean']:+.4f}** | "
            f"{arms[x]['mean_negatives'] - arms[y]['mean_negatives']:+.4f} |"
        )

    print("\nSame-prompt live variance, measured inside the experiment:")
    print("| pair | scenarios with byte-identical prompts | mean diff | scenarios that changed |")
    print("|---|---|---|---|")
    for x, y in (("c", "d"), ("b", "c")):
        same = [i for i in ids if arms[x]["draft_prompts"][i] == arms[y]["draft_prompts"][i]]
        diffs = [arms[y]["per_scenario"][i] - arms[x]["per_scenario"][i] for i in same]
        print(
            f"| ({x}) vs ({y}) | {len(same)}/{len(ids)} | "
            f"**{statistics.fmean(diffs):+.4f}** | {sum(1 for v in diffs if v)} |"
        )

    treated = [i for i in ids if arms["c"]["entry_in_prompt"][i]]
    control = [i for i in ids if not arms["c"]["entry_in_prompt"][i]]
    print("\n| subset | n | (b) | (c) | (d) |")
    print("|---|---|---|---|---|")
    for name, subset in (("lesson IN (c)'s prompt", treated), ("prompt identical to (b)", control)):
        cells = " | ".join(
            f"{statistics.fmean(arms[k]['per_scenario'][i] for i in subset):.4f}" for k in "bcd"
        )
        print(f"| {name} | {len(subset)} | {cells} |")

    total = sum(d["calls"] for d in arms.values())
    answered: dict[str, int] = {}
    for d in arms.values():
        for model, n in d["answered_by"].items():
            answered[model] = answered.get(model, 0) + n
    print(f"\narm calls: {total}   answered_by: {answered}")


if __name__ == "__main__":
    main()
