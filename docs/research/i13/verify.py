#!/usr/bin/env python
"""I13 — re-derive ADR 0156's floor, regression and verdict tables.

I13 committed its six raw `aef loop score --json` payloads (`floor-r{1,2,3}`,
`regress-r{1,2,3}`) and then typed the three tables of ADR 0156 by hand. That
is exactly the shape ADR 0188 deducted a point for: the numbers reach a reader
as prose with the data one directory away and nothing that regenerates them.
This script is the missing arithmetic, and `docs/research/measure.py` runs it.

`--verify` is the shared re-runner interface (ADR 0196): print the tables,
write nothing, make zero live calls. Every number below comes from the
committed JSON; nothing is re-scored.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

SCENARIOS = (
    "sum-13-cider-press",
    "sum-14-quarry-lake",
    "sum-15-bookbinder",
    "sum-16-cliff-path",
    "sum-17-clockmaker",
    "sum-18-heron-rookery",
)


def _load(prefix: str, root: Path) -> list[dict[str, Any]]:
    out = []
    for r in (1, 2, 3):
        payload = json.loads((root / f"{prefix}-r{r}.json").read_text())
        block = payload["validation"]
        out.append(
            {
                "repeat": r,
                "mean": float(block["mean"]),
                "stdev": float(block["stdev"]),
                "cost_tokens": int(block["cost_tokens"]),
                "per_scenario": block["per_scenario"],
                "cassette": payload["cassette"],
            }
        )
    return out


def _table(name: str, rows: list[dict[str, Any]]) -> tuple[float, float, float]:
    short = [s.split("-", 2)[0] + "-" + s.split("-")[1] for s in SCENARIOS]
    print(f"\n## The {name}\n")
    print("| repeat | mean | stdev | cost tokens | " + " | ".join(short) + " |")
    print("|---|---|---|---|" + "---|" * len(SCENARIOS))
    for row in rows:
        cells = " | ".join(f"{row['per_scenario'][s]:.2f}" for s in SCENARIOS)
        print(
            f"| {row['repeat']} | {row['mean']:.4f} | {row['stdev']:.4f} | "
            f"{row['cost_tokens']} | {cells} |"
        )
    means = [r["mean"] for r in rows]
    mom = statistics.fmean(means)
    spread = max(means) - min(means)
    sd = statistics.stdev(means)
    print(f"\n{name}: mean of means {mom:.4f} · spread {spread:.4f} · stdev of the means {sd:.4f}")
    return mom, spread, sd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="print the tables (the default)")
    parser.add_argument("--root", type=Path, default=HERE)
    args = parser.parse_args(argv)

    floor = _load("floor", args.root)
    regress = _load("regress", args.root)

    cassettes = {
        (r["cassette"]["hits"], r["cassette"]["misses"], r["cassette"]["on_miss"]) for r in floor
    }
    print(f"floor cassette, all three repeats: {sorted(cassettes)}")

    f_mom, f_spread, f_sd = _table("floor", floor)
    r_mom, r_spread, _ = _table("regression", regress)

    fall = f_mom - r_mom
    overlap = min(r["mean"] for r in floor) < max(r["mean"] for r in regress)
    print("\n## The verdict\n")
    print("| quantity | value |")
    print("|---|---|")
    print(f"| floor, mean of means | {f_mom:.4f} |")
    print(f"| regression, mean of means | {r_mom:.4f} |")
    print(f"| **fall** | **{fall:.4f}** |")
    print(f"| floor spread (max − min) | {f_spread:.4f} |")
    print(f"| floor stdev of the means | {f_sd:.4f} |")
    print(f"| fall ÷ floor stdev | {fall / f_sd:.2f} |")
    print(
        f"| every regression repeat vs every floor repeat | "
        f"**{'overlapping' if overlap else 'separated'}** "
        f"(floor min {min(r['mean'] for r in floor):.4f} "
        f"{'<' if overlap else '>='} regression max {max(r['mean'] for r in regress):.4f}) |"
    )
    print(
        f"\nfalsification (the fall must exceed the floor spread for dim 1 to move): "
        f"{'FIRED — dim 1 stays' if fall <= f_spread else 'did not fire'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
