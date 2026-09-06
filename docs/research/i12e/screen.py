"""P2 step 0 — the candidate-rule screen, offline, zero live calls.

Six candidate owner rules, each of the shape *"when the passage carries X, the
summary must carry X"*, evaluated against the summary recordings that already
exist. This is the disclosure `scenarios.py` describes: the recorded answers
were read before Rule A was written, to learn whether a second failure family
is reachable at all before spending quota on one that is not (ADR 0192's rule).

It reads the corpus and writes `results/screen.json`, so the table in ADR 0201
re-derives rather than being remembered.

Usage:
  PYTHONPATH=<worktree> <venv>/bin/python screen.py --out results/screen.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]

MONTHS = (
    r"(?i)\b(January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\b"
)
WEEKDAYS = r"(?i)\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
ATTRIBUTION = (
    r"(?i)\b(said|says|say|claim|alleg|report|assert|accus|according|disput|deni"
    r"|insist|unconfirmed|unverified)"
)

# name -> (does this rule APPLY to a passage?, what must the summary carry?)
CANDIDATES: dict[str, tuple[str, str]] = {
    "money written with the pound symbol": (r"\bpounds\b", "£"),
    "the month is carried": (MONTHS, MONTHS),
    "attribution is carried (Rule A)": (ATTRIBUTION, ATTRIBUTION),
    "the year is carried": (r"\b(19|20)\d\d\b", r"\b(19|20)\d\d\b"),
    "the percentage is carried": (r"(?i)per cent|%", r"(?i)per cent|%"),
    "the weekday is carried": (WEEKDAYS, WEEKDAYS),
}


def recordings() -> list[dict[str, str]]:
    """(split, id, passage, recorded answer) for every summary scenario on disk.

    The answer is read from the cassette rather than replayed, because the
    screen asks only what the model wrote; nothing here executes a graph.
    """
    rows: list[dict[str, str]] = []
    for path in sorted((REPO / "corpus").glob("*/sum-*.json")):
        data = json.loads(path.read_text())
        if data.get("graph_id") != "summary_agent":
            continue
        calls = data.get("model_calls") or []
        answer = ((calls[0].get("result") or {}) if calls else {}).get("content", "")
        rows.append(
            {
                "split": data["split"],
                "id": data["id"],
                "passage": data["initial_state"]["working_memory"].get("text", ""),
                "answer": str(answer).strip(),
            }
        )
    return rows


def screen(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, (precondition, required) in CANDIDATES.items():
        applies = [r for r in rows if re.search(precondition, r["passage"])]
        fails = [r for r in applies if not re.search(required, r["answer"])]
        out.append(
            {
                "rule": name,
                "precondition": precondition,
                "required": required,
                "applies": len(applies),
                "fails": len(fails),
                "rate": round(len(fails) / len(applies), 4) if applies else None,
                "failing": [r["id"] for r in fails],
                "failing_train": [r["id"] for r in fails if r["split"] == "train"],
                "failing_validation": [r["id"] for r in fails if r["split"] == "validation"],
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = recordings()
    table = screen(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"recordings": len(rows), "rules": table}, indent=2) + "\n")

    print(f"summary recordings screened: {len(rows)}   live calls: 0")
    for row in table:
        rate = "n/a" if row["rate"] is None else f"{row['rate']:.0%}"
        print(f"  {row['rule']:38s} applies={row['applies']:2d}  fails={row['fails']:2d} ({rate})")
        if row["failing"]:
            print(f"      {', '.join(row['failing'])}")


if __name__ == "__main__":
    main()
