"""Aggregate the eight arm-repeat JSONs into the ADR 0155 table."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

HERE = Path(__file__).parent / "results"


def main() -> None:
    table = {}
    total_calls = 0
    for arm in ("a", "b", "c", "d"):
        means = []
        per = {}
        calls = 0
        for r in (0, 1):
            data = json.loads((HERE / f"{arm}_r{r}.json").read_text())
            means.append(data["mean"])
            per[f"r{r}"] = data["per_scenario"]
            calls += data["calls"]
            entries = data["knowledge_entries"]
        total_calls += calls
        table[arm] = {
            "mean": round(statistics.fmean(means), 4),
            "repeats": [round(m, 4) for m in means],
            "spread": round(max(means) - min(means), 4),
            "calls": calls,
            "knowledge_entries": len(entries),
            "per_scenario": per,
        }

    spreads = [table[a]["spread"] for a in table]
    within_arm_spread = max(spreads)
    print(f"{'arm':>4} {'mean':>8} {'r0':>8} {'r1':>8} {'spread':>8} {'calls':>6} {'kn':>4}")
    for arm, row in table.items():
        print(
            f"{arm:>4} {row['mean']:>8.4f} {row['repeats'][0]:>8.4f} "
            f"{row['repeats'][1]:>8.4f} {row['spread']:>8.4f} {row['calls']:>6} "
            f"{row['knowledge_entries']:>4}"
        )
    print(f"\nmax within-arm spread (the noise floor this rig can see): {within_arm_spread:.4f}")
    print(f"total live calls: {total_calls}")

    b, c, d = table["b"]["mean"], table["c"]["mean"], table["d"]["mean"]
    a = table["a"]["mean"]
    print(f"\n(b) - (a) = {b - a:+.4f}   [retrieval of raw records vs none]")
    print(f"(c) - (b) = {c - b:+.4f}   [knowledge layer vs raw records]")
    print(f"(d) - (c) = {d - c:+.4f}   [LLM reflection vs rule-based]")
    print(f"\nfalsification (c) <= (b): {'FIRED' if c <= b else 'did not fire'}")
    print(f"falsification (d) <= (c): {'FIRED' if d <= c else 'did not fire'}")
    print(
        f"(c)-(b) exceeds the spread: "
        f"{'yes' if abs(c - b) > within_arm_spread else 'NO — not a gain'}"
    )
    print(
        f"(d)-(c) exceeds the spread: "
        f"{'yes' if abs(d - c) > within_arm_spread else 'NO — not a gain'}"
    )

    out = Path(__file__).parent / "results" / "summary.json"
    out.write_text(
        json.dumps(
            {
                "arms": table,
                "max_within_arm_spread": within_arm_spread,
                "total_calls": total_calls,
                "deltas": {
                    "b_minus_a": round(b - a, 4),
                    "c_minus_b": round(c - b, 4),
                    "d_minus_c": round(d - c, 4),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
