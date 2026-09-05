"""The control ADR 0119 demands: does the scan actually scan?

A zero from a scanner that never ran and a zero from a clean corpus look the
same. This plants credential-shaped tokens into a run's objective and working
memory and re-runs the same policy, and it checks marlin's own subscription
UUID — the identifier its AGENTS.md boundary rule is written around — against
the default pattern list.

Two modes:

* `<runs-dir>` — the original: plant into a **real** recorded run of the M6
  pilot. This needs marlin's `.aef/runs`, which is deliberately not committed
  (ADR 0163: "the scan's output is what is committed; no raw recorded run
  is"), so it cannot run in CI or on a fresh clone.
* `--verify` — the shared re-runner interface (ADR 0196). Same policy, same
  planted tokens, same three controls, against a stand-in objective instead of
  the uncommitted run. The counts ADR 0163 §5 publishes are properties of the
  patterns and the plants, not of the surrounding sentence, so this re-derives
  them from committed data with zero live calls. The stand-in is stated rather
  than hidden: control 1's trailing text differs, its numbers do not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.harness.harvest import load_runs  # noqa: E402
from aef.harness.redaction import RedactionPolicy  # noqa: E402
from aef.state import AEFState  # noqa: E402

PLANTS = {
    "email": "ingest-ops@marlindataco.example.com",
    "api_key": "sk_live_9fJq2LmZ4tRx8Vb1Nc7Hd0Ke",
    "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc",
    "aws_key": "AKIAIOSFODNN7EXAMPLE",
    "opaque_secret": "aG9yaXpvbnRhbGx5U2NhbGVkTWFybGluU2VjcmV0MDEyMzQ1Njc4OQ",
}

# Every shape N6 added (ADR 0197), so the control covers the whole list rather
# than the half of it that existed when M6 ran.
PLANTS_N6 = {
    "uuid": "7e16b0bb-b75a-4a16-9765-839cf1b96755",
    "jwt": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    ),
    "github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB",
    "slack_token": "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
    "openai_key": "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEf",
    "connection_string": "postgres://svcuser:hunter2correct@db.internal.example:5432/marlin",
}

# The false positives ADR 0126 removed and this control must keep out.
NEGATIVES = {
    "hyphenated English objective": (
        "migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime"
    ),
    "long snake_case identifier": (
        "test_a_downstream_node_counts_as_a_recurrence_of_its_own_lesson"
    ),
    "the cassette's own SHA digest": "sha256:" + "a3f5" * 16,
}

STANDIN = "Answer the boundary question for the marlin ingestion service"


def controls(objective: str, working_memory: dict[str, object]) -> None:
    policy = RedactionPolicy()

    print("== control 1: the same policy over the SAME run with tokens planted in the objective")
    for label, planted in {**PLANTS, **PLANTS_N6}.items():
        state = AEFState(
            run_id="control",
            agent_id="control",
            objective=f"{objective} (contact {planted})",
            working_memory=dict(working_memory),
        )
        _, count = policy.redact_state(state)
        text, _ = policy.redact_text(state.objective)
        print(f"  {label:19} substitutions={count}  -> ...{text[-46:]}")

    print("\n== control 2: secret-shaped working-memory keys are dropped outright")
    state = AEFState(
        run_id="control",
        agent_id="control",
        objective=objective,
        working_memory={**working_memory, "api_key": "x", "token": "y", "keep_me": "z"},
    )
    redacted, count = policy.redact_state(state)
    print(
        f"  before {sorted(state.working_memory)}  ->  "
        f"after {sorted(redacted.working_memory)}  (count={count})"
    )

    print("\n== control 3: the false positives that must still NOT match")
    for label, text in NEGATIVES.items():
        hits = policy.find({"objective": text})
        print(f"  {label:31} matched={list(hits) or 'nothing'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="?", type=Path, help="marlin's .aef/runs (not committed)")
    parser.add_argument("--verify", action="store_true", help="run against a stand-in objective")
    args = parser.parse_args(argv)

    if args.runs is None and not args.verify:
        parser.error("one of <runs-dir> or --verify")

    if args.runs is not None:
        run = sorted(load_runs(args.runs), key=lambda r: r.at)[0]
        controls(run.initial_state.objective, dict(run.initial_state.working_memory))
    else:
        print(f"stand-in objective (the raw runs are not committed): {STANDIN!r}\n")
        controls(STANDIN, {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
