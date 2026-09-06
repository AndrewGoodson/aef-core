"""P2 — read the arm JSONs and print every table ADR 0201 quotes.

The pre-registered rule is `docs/research/i12e/prereg.txt`, committed before
the first live call, and it is evaluated here rather than by hand:

    dimension 2 moves 14 -> 17 iff a second knowledge entry formed from a
    DIFFERENT signature, AND (d) - (b) on the mean is more than the larger of
    the two arms' repeat spreads, AND (d) >= (b) on the owner-check negatives.
    14 -> 15 if a second entry formed and that band fails. +0 if none formed.

Arm (c) has no JSON of its own and is not missing. `dry_identity.py` hashed
every rendered prompt of every arm offline: (c) at the shipped
`knowledge_boost=0.0` and (b) produce ONE sha256 over all twenty-one prompts,
so (b)'s live repeats ARE (c)'s live repeats. This script prints (c) as a row
labelled with that identity rather than inventing a third sample.

`--verify` (ADR 0196's shared interface) prints and writes nothing extra —
it is the same run — and `sys.argv[1]` is taken as the results root only when
it is not a flag, which is the bug ADR 0196 caught in this file's ancestor.

Usage:
  <venv>/bin/python aggregate.py [results-dir]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

# The ten owner-check negatives. `arms.py::NEGATIVES` derives and asserts the
# same tuple from the corpus itself on every run; this copy is for the tables.
NEGATIVES = (
    "sum-13-cider-press",
    "sum-14-quarry-lake",
    "sum-16-cliff-path",
    "sum-17-clockmaker",
    "sum-30-ganister-tarn",
    "sum-33-cotterdale-bus",
    "sum-35-priory-gatehouse",
    "sum-36-larkfield-quarry",
    "sum-46-thwaite-lane-bridge",
    "sum-47-eller-beck-hatchery",
)

LABEL = {
    "a": "(a) no retrieve",
    "b": "(b) raw records",
    "c": "(c) + knowledge @ 0.0 (shipped)",
    "d": "(d) + knowledge @ 16.0",
}

LESSONS = ("ruleA", "both", "cap")


def load(root: Path) -> dict[str, list[dict]]:
    arms: dict[str, list[dict]] = {}
    for path in sorted(root.glob("[abd]_r*.json")):
        arms.setdefault(path.name[0], []).append(json.loads(path.read_text()))
    for runs in arms.values():
        runs.sort(key=lambda d: d["repeat"])
    # Arm (c) IS arm (b): identical rendered prompts, proved offline.
    arms["c"] = arms["b"]
    return arms


def spread(values: list[float]) -> float:
    return max(values) - min(values) if len(values) > 1 else 0.0


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent / "results"
    arms = load(root)
    ids = list(arms["a"][0]["per_scenario"])
    n_neg = sum(1 for i in ids if i in NEGATIVES)

    print("## The store the arms ran against\n")
    print("| signature | runs | confidence | runs_since_last_seen at seed |")
    print("|---|---|---|---|")
    first = arms["d"][0]
    before = first["entry_before"][ids[0]]
    for entry in first["seeded_entries"]:
        state = before.get(entry, {})
        print(
            f"| `{entry}` | {state.get('occurrences')} | "
            f"{state.get('confidence')} | {state.get('runs_since_last_seen')} |"
        )

    print("\n## Per repeat\n")
    print(
        f"| arm | repeat | boost | mean | negatives (n={n_neg}) | "
        f"rest (n={len(ids) - n_neg}) | lessons in prompt | calls | prompt sha256 |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for arm in "abcd":
        for d in arms[arm]:
            shown = {
                name: sum(1 for v in d["lessons_rendered"].values() if name in v)
                for name in LESSONS
            }
            cell = ", ".join(f"{k} {v}/{len(ids)}" for k, v in shown.items() if v)
            note = " *(is (b))*" if arm == "c" else ""
            print(
                f"| {LABEL[arm]}{note} | {d['repeat']} | "
                f"{0.0 if arm == 'c' else d['knowledge_boost']} | "
                f"{d['mean']:.4f} | {d['mean_negatives']:.4f} | {d['mean_positives']:.4f} | "
                f"{cell or 'none'} | {0 if arm == 'c' else d['calls']} | "
                f"`{d['draft_prompt_sha256'][:16]}` |"
            )

    print("\n## Per arm (mean of repeats), with the repeat spread\n")
    print("| arm | repeats | mean | spread | negatives | neg spread | live calls |")
    print("|---|---|---|---|---|---|---|")
    agg: dict[str, dict[str, float]] = {}
    for arm in "abcd":
        means = [d["mean"] for d in arms[arm]]
        negs = [d["mean_negatives"] for d in arms[arm]]
        agg[arm] = {
            "mean": statistics.fmean(means),
            "spread": spread(means),
            "neg": statistics.fmean(negs),
            "neg_spread": spread(negs),
        }
        calls = 0 if arm == "c" else sum(d["calls"] for d in arms[arm])
        print(
            f"| {LABEL[arm]} | {len(means)} | **{agg[arm]['mean']:.4f}** | "
            f"{agg[arm]['spread']:.4f} | {agg[arm]['neg']:.4f} | "
            f"{agg[arm]['neg_spread']:.4f} | {calls} |"
        )

    print("\n## Per scenario (mean over that arm's repeats), and which lesson reached it\n")
    print("| scenario | (a) | (b)=(c) | (d) | lessons in (d)'s prompt |")
    print("|---|---|---|---|---|")
    for i in ids:
        neg = " **NEG**" if i in NEGATIVES else ""
        cells = " | ".join(
            f"{statistics.fmean(d['per_scenario'][i] for d in arms[a]):.2f}" for a in "abd"
        )
        rendered = sorted({x for d in arms["d"] for x in d["lessons_rendered"][i]})
        print(f"| `{i}`{neg} | {cells} | {', '.join(rendered) or '—'} |")

    print("\n## Deltas\n")
    print("| comparison | delta (mean) | delta (negatives) |")
    print("|---|---|---|")
    for x, y in (("b", "a"), ("c", "b"), ("d", "c"), ("d", "b"), ("d", "a")):
        print(
            f"| ({x}) − ({y}) | **{agg[x]['mean'] - agg[y]['mean']:+.4f}** | "
            f"{agg[x]['neg'] - agg[y]['neg']:+.4f} |"
        )

    print("\n## The pre-registered rule\n")
    bar = max(agg["b"]["spread"], agg["d"]["spread"])
    neg_bar = max(agg["b"]["neg_spread"], agg["d"]["neg_spread"])
    d_mean = agg["d"]["mean"] - agg["b"]["mean"]
    d_neg = agg["d"]["neg"] - agg["b"]["neg"]
    entries = len(first["seeded_entries"])
    print(f"    knowledge entries seeded    =  {entries}")
    print(f"    (d) − (b) on the mean       = {d_mean:+.4f}")
    print(f"    larger repeat spread (BAR)  =  {bar:.4f}")
    print(f"    (d) − (b) on the negatives  = {d_neg:+.4f}")
    print(f"    larger negatives spread     =  {neg_bar:.4f}")
    if entries < 2:
        verdict = "+0 (no second lesson formed)"
    elif d_mean > bar and d_neg >= 0:
        verdict = "14 -> 17"
    else:
        verdict = "14 -> 15 (the second lesson exists; the arms do not separate)"
    print(f"\n    BRANCH: {verdict}")
    print(f"    knob trigger ((d) − (c) > BAR): {agg['d']['mean'] - agg['c']['mean'] > bar}")

    print("\n## Same-prompt live variance (repeats of one arm)\n")
    print("| arm | prompt hashes | mean spread | scenarios whose score differed across repeats |")
    print("|---|---|---|---|")
    for arm in "abd":
        hashes = {d["draft_prompt_sha256"][:16] for d in arms[arm]}
        changed = sum(1 for i in ids if len({d["per_scenario"][i] for d in arms[arm]}) > 1)
        print(
            f"| {LABEL[arm]} | {len(hashes)} distinct | {agg[arm]['spread']:.4f} | "
            f"{changed}/{len(ids)} |"
        )

    print("\n## Which lesson was where, in arm (d)\n")
    print("| repeat | ranks at scenario 1 | ranks at the last scenario | all three in prompt |")
    print("|---|---|---|---|")
    for d in arms["d"]:
        allthree = sum(1 for v in d["lessons_rendered"].values() if len(v) == 3)
        print(
            f"| {d['repeat']} | {d['entry_rank'][ids[0]]} | {d['entry_rank'][ids[-1]]} | "
            f"{allthree}/{len(ids)} |"
        )

    print("\n## What each arm's failures were, by check\n")
    print("| arm | repeat | max_words only | regex only | both | clean |")
    print("|---|---|---|---|---|---|")
    for arm in "abd":
        for d in arms[arm]:
            counts = {"cap": 0, "regex": 0, "both": 0, "clean": 0}
            for keys in d["recorded_failures"].values():
                has_cap = any(k.endswith(":max_words") for k in keys)
                has_re = any(k.endswith(":regex") for k in keys)
                if has_cap and has_re:
                    key = "both"
                elif has_cap:
                    key = "cap"
                elif has_re:
                    key = "regex"
                else:
                    key = "clean"
                counts[key] += 1
            print(
                f"| {LABEL[arm]} | {d['repeat']} | {counts['cap']} | {counts['regex']} | "
                f"{counts['both']} | {counts['clean']} |"
            )

    total = sum(d["calls"] for arm in "abd" for d in arms[arm])
    answered: dict[str, int] = {}
    for arm in "abd":
        for d in arms[arm]:
            for model, n in d["answered_by"].items():
                answered[model] = answered.get(model, 0) + n
    print(f"\narm calls: {total}   answered_by: {answered}")


if __name__ == "__main__":
    main()
