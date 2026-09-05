"""N2 — read the arm JSONs and print every table ADR 0193 quotes.

The pre-registered rule, stated in the worker's brief before any live call and
evaluated here rather than by hand:

    dim 2 moves 12 -> 14 iff (c) > (b) on the mean by MORE than the larger of
    the two arms' repeat spreads AND (c) >= (b) on the owner-check negatives.
    12 -> 13 iff the negatives alone clear it. Otherwise +0, and the ADR says
    the knowledge layer does not help this agent on this corpus.

Unlike ADR 0184's run this one affords **three repeats of each** of (b) and
(c), so the two spreads are estimated from equal samples and neither arm's
mean is more precise than the other's.

Usage:
  <venv>/bin/python aggregate.py [results-dir]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

# The eight owner-check negatives of the one-model corpus (ADR 0186). Kept in
# step with `arms.py::NEGATIVES`, which derives and asserts them from the
# corpus itself on every run.
NEGATIVES = (
    "sum-13-cider-press",
    "sum-14-quarry-lake",
    "sum-16-cliff-path",
    "sum-17-clockmaker",
    "sum-30-ganister-tarn",
    "sum-33-cotterdale-bus",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
)

LABEL = {
    "a": "(a) no retrieve",
    "b": "(b) raw records",
    "c": "(c) + knowledge @ boost 8.0",
}


def load(root: Path) -> dict[str, list[dict]]:
    arms: dict[str, list[dict]] = {}
    for path in sorted(root.glob("[abc]_r*.json")):
        arm = path.name[0]
        arms.setdefault(arm, []).append(json.loads(path.read_text()))
    for runs in arms.values():
        runs.sort(key=lambda d: d["repeat"])
    return arms


def spread(values: list[float]) -> float:
    return max(values) - min(values) if len(values) > 1 else 0.0


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results"
    arms = load(root)
    ids = list(arms["a"][0]["per_scenario"])

    print("## Per repeat\n")
    n_neg = sum(1 for i in ids if i in NEGATIVES)
    print(
        f"| arm | repeat | boost | mean | negatives (n={n_neg}) | "
        f"rest (n={len(ids) - n_neg}) | in prompt | calls |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for arm in "abc":
        for d in arms[arm]:
            shown = sum(1 for v in d["entry_in_prompt"].values() if v)
            print(
                f"| {LABEL[arm]} | {d['repeat']} | {d['knowledge_boost']} | "
                f"{d['mean']:.4f} | {d['mean_negatives']:.4f} | {d['mean_positives']:.4f} | "
                f"{shown}/{len(ids)} | {d['calls']} |"
            )

    print("\n## Per arm (mean of repeats), with the repeat spread\n")
    print("| arm | repeats | mean | spread | negatives | neg spread | calls |")
    print("|---|---|---|---|---|---|---|")
    agg: dict[str, dict[str, float]] = {}
    for arm in "abc":
        means = [d["mean"] for d in arms[arm]]
        negs = [d["mean_negatives"] for d in arms[arm]]
        agg[arm] = {
            "mean": statistics.fmean(means),
            "spread": spread(means),
            "neg": statistics.fmean(negs),
            "neg_spread": spread(negs),
        }
        print(
            f"| {LABEL[arm]} | {len(means)} | **{agg[arm]['mean']:.4f}** | "
            f"{agg[arm]['spread']:.4f} | {agg[arm]['neg']:.4f} | "
            f"{agg[arm]['neg_spread']:.4f} | {sum(d['calls'] for d in arms[arm])} |"
        )

    print("\n## Per scenario (mean over that arm's repeats)\n")
    header = " | ".join(f"({a})" for a in "abc")
    print(f"| scenario | {header} | lesson in (c)'s prompt |")
    print("|---|---|---|---|---|")
    for i in ids:
        neg = " **NEG**" if i in NEGATIVES else ""
        cells = " | ".join(
            f"{statistics.fmean(d['per_scenario'][i] for d in arms[a]):.2f}" for a in "abc"
        )
        shown = sum(1 for d in arms["c"] if d["entry_in_prompt"][i])
        print(f"| `{i}`{neg} | {cells} | {shown}/{len(arms['c'])} |")

    print("\n## Deltas\n")
    print("| comparison | delta (mean) | delta (negatives) |")
    print("|---|---|---|")
    for x, y in (("b", "a"), ("c", "b"), ("c", "a")):
        print(
            f"| ({x}) − ({y}) | **{agg[x]['mean'] - agg[y]['mean']:+.4f}** | "
            f"{agg[x]['neg'] - agg[y]['neg']:+.4f} |"
        )

    print("\n## The pre-registered rule\n")
    bar = max(agg["b"]["spread"], agg["c"]["spread"])
    neg_bar = max(agg["b"]["neg_spread"], agg["c"]["neg_spread"])
    d_mean = agg["c"]["mean"] - agg["b"]["mean"]
    d_neg = agg["c"]["neg"] - agg["b"]["neg"]
    print(f"    (c) − (b) on the mean       = {d_mean:+.4f}")
    print(f"    larger repeat spread        =  {bar:.4f}")
    print(f"    (c) − (b) on the negatives  = {d_neg:+.4f}")
    print(f"    larger negatives spread     =  {neg_bar:.4f}")
    if d_mean > bar and d_neg >= 0:
        verdict = "12 -> 14"
    elif d_neg > neg_bar:
        verdict = "12 -> 13"
    else:
        verdict = "+0 (dimension 2 does not move)"
    print(f"\n    BRANCH: {verdict}")

    print("\n## Same-prompt live variance (repeats of one arm, identical prompt hashes)\n")
    print("| arm | prompt hashes | mean spread | scenarios whose score differed across repeats |")
    print("|---|---|---|---|")
    for arm in "abc":
        hashes = {d["draft_prompt_sha256"][:16] for d in arms[arm]}
        changed = sum(1 for i in ids if len({d["per_scenario"][i] for d in arms[arm]}) > 1)
        print(
            f"| {LABEL[arm]} | {len(hashes)} distinct | {agg[arm]['spread']:.4f} | "
            f"{changed}/{len(ids)} |"
        )

    print("\n## The entry's rank trajectory in arm (c)\n")
    print(f"| repeat | rank @ scenario 1 | rank @ scenario {len(ids)} | in prompt | max rank |")
    print("|---|---|---|---|---|")
    for d in arms["c"]:
        ranks = [d["entry_rank"][i] for i in ids]
        shown = sum(1 for v in d["entry_in_prompt"].values() if v)
        seen = [r for r in ranks if r is not None]
        print(
            f"| {d['repeat']} | {ranks[0]} | {ranks[-1]} | {shown}/{len(ids)} | "
            f"{max(seen) if seen else '-'} |"
        )

    total = sum(d["calls"] for runs in arms.values() for d in runs)
    answered: dict[str, int] = {}
    for runs in arms.values():
        for d in runs:
            for model, n in d["answered_by"].items():
                answered[model] = answered.get(model, 0) + n
    print(f"\narm calls: {total}   answered_by: {answered}")


if __name__ == "__main__":
    main()
