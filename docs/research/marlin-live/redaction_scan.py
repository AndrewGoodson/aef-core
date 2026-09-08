"""The redaction scan on marlin's real recorded runs, and its control.

Three things, in this order, because the third is what makes the first two
mean anything:

1. what the SHIPPED policy counts over all ten recorded runs — the objective
   the model was sent, the answer it wrote, and the model-call messages the
   cassette holds (which is where marlin's persona bodies live);
2. what it does NOT match on a repo whose content is Azure resource names,
   county endpoints and Key Vault secret NAMES;
3. the planted-fault control — one credential-shaped token at a time — because
   a zero from a dead scanner and a zero from a clean repo are the same
   number.

The control's planted values are synthetic: none is a credential of this or
any repository.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a1aa5766514609859")

from aef.harness.redaction import DEFAULT_PATTERNS, RedactionPolicy  # noqa: E402

# Shapes a marlin artefact could plausibly carry. Every VALUE here is
# synthetic — invented for this control — and none is a real credential.
CONTROL = (
    ("email", "Escalate to permits-ops@example.invalid about the cap."),
    ("api_key", "Escalate to sk-ant-api03-Zq7Yb2Nn4Rr8Tt1Uu6Vv3Ww9Xx5Yy0Zz2Aa about the cap."),
    ("bearer", "Escalate to Bearer abcdefghijklmnopqrstuvwxyz012345 about the cap."),
    ("aws_key", "Escalate to AKIAQ7WZ2N4R8T1U6V3W about the cap."),
    ("github_token", "Escalate to ghp_0123456789abcdefghijklmnopqrstuvwxyz about the cap."),
    ("slack_token", "Escalate to xoxb-1234567890-abcdefghijkl about the cap."),
    ("jwt", "Escalate to eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K about the cap."),
    (
        "connection_string",
        "Escalate to mssql://marlin_ro:Pw0rdPw0rd@marlin-sql.example.invalid/db about the cap.",
    ),
    (
        "uuid (a subscription-shaped id)",
        "Escalate to 0f3b1c2d-4e5f-4a6b-8c9d-0e1f2a3b4c5d about the cap.",
    ),
    ("opaque_secret", "Escalate to Zq7Yb2Nn4Rr8Tt1Uu6Vv3Ww9Xx5Yy0Zz2Aa4Bb6Cc about the cap."),
)

# What must NOT be redacted: this repository's public, non-secret vocabulary.
NEGATIVE = (
    (
        "county endpoint",
        "https://capeims.capecoral.gov/arcgis/rest/services/OpenData/OpenData/MapServer/1",
    ),
    ("resource group", "resource group rg-marlin-dev, tags project=marlin costCenter=marlin"),
    (
        "key vault secret NAMES",
        "accela-app-id, accela-app-secret, accela-username, accela-password",
    ),
    ("cursor field", "cursor_field: last_edited_date, grace_days: 7"),
    ("the wrapper", "./infra/az-marlin group show --name rg-marlin-dev"),
    ("a count query", "returnCountOnly=true returned 41377; fetched 41290"),
)


def texts_of(run: dict) -> list[tuple[str, str]]:
    """Every string a scenario built from this run would carry."""
    out = [("objective", run["initial_state"]["objective"])]
    for i, mc in enumerate(run.get("model_calls", [])):
        for j, m in enumerate(mc.get("request", {}).get("messages", []) or []):
            out.append((f"model_call[{i}].messages[{j}].{m.get('role')}", m.get("content", "")))
        out.append((f"model_call[{i}].completion", json.dumps(mc.get("result", ""))))
    for t in run["trace"]:
        wm = t.get("delta", {}).get("working_memory", {})
        for k, v in wm.items():
            if isinstance(v, str):
                out.append((f"trace.{t['node_id']}.working_memory.{k}", v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    policy = RedactionPolicy()
    print("policy patterns:", ", ".join(label for label, _ in DEFAULT_PATTERNS))
    print("working_memory keys dropped outright:", list(policy.drop_working_memory_keys))

    print("\n== 1. the shipped policy over every recorded run")
    total = 0
    hits: dict[str, int] = {}
    runs = sorted(pathlib.Path(args.runs).glob("*.json"))
    for p in runs:
        d = json.loads(p.read_text())
        subs = 0
        for _, text in texts_of(d):
            red, n = policy.redact_text(text)
            subs += n
            if n:
                for label, rx in policy._compiled:  # noqa: SLF001 - the point is which label
                    k = len(rx.findall(text))
                    if k:
                        hits[label] = hits.get(label, 0) + k
        total += subs
        print(f"   {p.name[:8]}  substitutions={subs}")
    print(f"   TOTAL substitutions over {len(runs)} run(s): {total}   by label: {hits or '{}'}")

    print("\n== 2. what it does NOT match (this repo's public vocabulary)")
    for name, text in NEGATIVE:
        red, n = policy.redact_text(text)
        why = [label for label, rx in policy._compiled if rx.search(text)]  # noqa: SLF001
        tail = f"  <- FALSE POSITIVE, matched {why}: {red[:80]}" if n else ""
        print(f"   {name:26s} substitutions={n}  -> {text[:72]}{tail}")

    print("\n== 3. the control — one planted, synthetic credential at a time")
    caught = 0
    for name, text in CONTROL:
        red, n = policy.redact_text(text)
        caught += n > 0
        print(f"   {name:32s} substitutions={n}  -> {red[:88]}")
    print(f"\n   {caught} of {len(CONTROL)} planted shapes caught. The scan scans.")

    print("\n== 4. marlin's own agentic surface, scanned where it would reach a scenario")
    repo = pathlib.Path(args.repo)
    for rel in sorted(
        [pathlib.Path("AGENTS.md")] + sorted(pathlib.Path(".claude/agents") / f.name for f in
                                             (repo / ".claude/agents").glob("*.md"))
    ):
        text = (repo / rel).read_text()
        labels: dict[str, int] = {}
        for label, rx in policy._compiled:  # noqa: SLF001
            k = len(rx.findall(text))
            if k:
                labels[label] = k
        flag = "  <- would be redacted if this persona ran" if labels else ""
        print(f"   {str(rel):42s} {labels or '{}'}{flag}")
    print(
        "   the persona this pilot ran is .claude/agents/source-agent.md; the "
        "scan above says what it carries."
    )

    from aef.state import AEFState  # noqa: PLC0415 - kept beside its one use

    st = AEFState(
        run_id="00000000-0000-4000-8000-000000000000",
        agent_id="marlin-source",
        objective="x",
        working_memory={"api_key": "x", "token": "y", "cursor_field": "last_edited_date"},
    )
    red, n = policy.redact_state(st)
    print(
        f"   working-memory keys: before {sorted(st.working_memory)} -> "
        f"after {sorted(red.working_memory)} (substitutions+drops {n})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
