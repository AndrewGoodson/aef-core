"""Step 5: the redaction scan over every recorded run, and its planted-fault
control. Zero live model calls.

Three parts.

1. The counts `aef loop harvest` itself reports, with the shipped default
   policy — on the runs as shipped (arm 0) and with the one missing input
   supplied (arm 1), because the redaction step runs AFTER the determinism
   re-check and a rejected run never reaches it.
2. The policy applied DIRECTLY to all five runs' inputs and answers, so the
   count is not an artefact of which runs got that far.
3. The control. A zero from a dead scanner looks exactly like a zero from a
   clean repo, so each credential shape is planted into a real objective, one
   at a time, and the scanner is watched to catch it. Then the shapes THIS
   repo actually carries — vendor domains, prices, a compound slug — are put
   through the same policy, and what it does NOT match is stated.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
sys.path.insert(0, str(W / "peptide"))

from agents.migrated.price_freshness_reviewer.graph import build_graph  # noqa: E402

from aef.harness import harvest as H  # noqa: E402
from aef.harness.harvest import (  # noqa: E402
    DEFAULT_REDACTION,  # noqa: E402
    harvest,
    load_runs,
)
from aef.harness.memory_store import FileMemoryStore  # noqa: E402
from aef.services.memory.in_memory import InMemoryMemoryStore  # noqa: E402

GRAPH = build_graph()
RUNS = W / "runs"
MEM = W / "state" / "memory.jsonl"
POLICY = DEFAULT_REDACTION

runs = sorted(load_runs(RUNS), key=lambda r: r.at)
order = [r.run_id for r in runs]
all_records = list(FileMemoryStore(MEM)._load())
original = H._reexecution_services


def patched(scenario, isolation=(), provider_name=""):  # type: ignore[no-untyped-def]
    services = original(scenario, isolation, provider_name)
    store = InMemoryMemoryStore()
    earlier = set(order[: order.index(scenario.id)])
    for rec in all_records:
        if rec.run_id in earlier:
            store.write(rec)
    return H.agent_services(
        clock=H._fixed_clock(scenario), memory=store, model_provider=services.model_provider
    )


print(f"policy patterns: {', '.join(label for label, _ in POLICY.patterns)}")
print(f"working_memory keys dropped outright: {list(POLICY.drop_working_memory_keys)}")
print(f"{len(runs)} recorded run(s)\n")

print("== 1. what harvest itself counts, with redaction ON (the shipped default)")
for label, patch in (("arm 0 — as shipped", False), ("arm 1 — + the memory the run saw", True)):
    corpus = W / f"redact-{'1' if patch else '0'}-corpus"
    state = W / f"redact-{'1' if patch else '0'}-state"
    corpus.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    if patch:
        H._reexecution_services = patched  # type: ignore[assignment]
    try:
        out = harvest(RUNS, corpus, GRAPH, now=datetime.now(UTC), include_successes=True)
    finally:
        H._reexecution_services = original  # type: ignore[assignment]
    print(f"   {label}")
    print(f"     re-executed (offered to the re-check) : {len(runs)}")
    print(f"     admitted   (promoted)                 : {len(out.promoted)}")
    print(f"     rejected   (non-deterministic)        : {len(out.rejected_nondeterministic)}")
    print(f"     refused    (behaviour changed under redaction): "
          f"{len(out.rejected_redaction_changed_behaviour)}")
    print(f"     refused    (a secret survived redaction)     : "
          f"{len(out.rejected_unredactable)}")
    print(f"     redactions (substitutions made)              : {out.redactions}")
    print(f"     already in the corpus (skipped)              : {len(out.skipped_existing)}")
    print(f"     held back by the daily limit ({out.daily_limit})          : "
          f"{len(out.skipped_rate_limited)}")

print()
print("== 2. the policy applied directly to all five runs (the re-check reaches only some)")
tot_in = tot_ans = tot_wm = 0
for r in runs:
    _, n_in = POLICY.redact_state(r.initial_state)
    wm: dict = {}
    for step in r.trace:
        for k, v in (getattr(step.delta, "working_memory", None) or {}).items():
            wm[k] = v
    answer = str(wm.get("prompt_agent", ""))
    _, n_ans = POLICY.redact_text(answer)
    hits_out = POLICY.find(wm)
    tot_in += n_in
    tot_ans += n_ans
    print(f"   {r.run_id[:8]}  INPUT subs={n_in}  ANSWER subs={n_ans}  "
          f"labels matched in the recorded working memory={list(hits_out)}")
_totals = json.dumps(
    {"input_subs": tot_in, "answer_subs": tot_ans, "wm_dropped": tot_wm}
)
print(f"   totals: {_totals}")

print()
print("== 3. the control — a zero from a dead scanner looks like a zero from a clean repo")
base = runs[0].initial_state.objective
planted = {
    "email": "pricing-ops@peptideindex.com",
    "api_key": "sk_live_9fJq2mXbTz7Wc4Rv0LpH6sYd",
    "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    "aws_key": "AKIAQ7Z2M4XPLV6TR3WD",
    "opaque_secret": "b7Xk92LmQz4RtY8UvNc3JhWd5FgS1AoE6PiKzT0B",
}
for label, token in planted.items():
    text = f"{base} Escalate to {token}."
    out, n = POLICY.redact_text(text)
    tail = out[len(out) - 60 :]
    print(f"   {label:<14} substitutions={n}  -> ...{tail}")

print()
print("   secret-shaped working-memory keys:")
wm_before = {"api_key": "x", "token": "y", "vendor_domain": "peptideplugs.com"}
st = runs[0].initial_state.model_copy(update={"working_memory": dict(wm_before)})
st2, n = POLICY.redact_state(st)
print(f"     before {sorted(wm_before)}  ->  after {sorted(st2.working_memory)}  (count={n})")

print()
print("   what this repo's OWN identifier shapes do under the same policy:")
for label, sample in (
    ("vendor domain", "peptideplugs.com"),
    ("vendor domain (multi-label)", "skyepeptides.us.com"),
    ("compound slug", "bpc-157"),
    ("price per mg", "price_per_mg_usd 1.6667"),
    ("scrape date", "scrape_date 2026-08-12"),
    ("a whole real row", 'peptaura.com / bpc-157 "10 × 10mg vials" @ $0.96/mg, 2026-08-14'),
    ("an operator email in prose", "reached pricing-ops@peptideindex.com about the delisting"),
    # THE RESIDUAL. This repo commits an Azure subscription UUID in
    # infra/jobs/*.yaml. The real value is deliberately NOT reproduced here;
    # what is reproduced is its SHAPE, which is what the policy sees.
    ("an azure subscription UUID (shape only)",
     "/subscriptions/00000000-1111-2222-3333-444444444444/resourceGroups/rg-example"),
    ("a bare UUID (shape only)", "00000000-1111-2222-3333-444444444444"),
):
    out, n = POLICY.redact_text(sample)
    print(f"     {label:<28} substitutions={n}  -> {out}")
