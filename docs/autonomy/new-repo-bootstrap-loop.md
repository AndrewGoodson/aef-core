# New-repo bootstrap loop — copy-paste prompt

This is the ready-to-paste prompt for a **new repo adopting aef-core**. It
takes a fresh repo from zero to a green, aef-core-wired agent running the
self-improving loop under the HARD-STOP safety gates.

**Any harness.** The `/loop` prefix is Claude Code's self-scheduling command;
the prompt body is harness-agnostic. Use it as:
- **Claude Code** — paste the whole block (keep the `/loop` prefix).
- **Codex / Cursor / GitHub Copilot / other** — drop the `/loop ` prefix and
  paste the rest as an ordinary agent instruction; run the phases in order.
  The green bar and HARD-STOP gates are identical regardless of harness.

Prereq: the target repo has (or will `pip install`) `aef-core`, and you have
push rights to that repo's own remote only.

---

```
/loop Bootstrap THIS repo onto aef-core and bring it to a green, wired agent, then run the
bounded self-improving loop. Work autonomously; obey the HARD-STOP gates below.

PHASE 0 — GROUND:
  - pip install aef-core  (add [anthropic]/[mem0] extras only when wiring those backends)
  - If no aef.yaml/CLAUDE.md yet: run `aef adopt` in the repo root. It writes six
    never-overwrite files: CLAUDE.md, aef.yaml, aef_adapter.py, AEF_MIGRATION_CHECKLIST.md,
    AGENT_INTEGRATION.md, AUTONOMY.md.
  - Read AGENT_INTEGRATION.md and AUTONOMY.md in full before writing any code. They are the
    contract. AUTONOMY.md's HARD-STOP gates govern everything below.
  - `aef doctor` — fix every [FAIL]; [WARN] advisories optional.

PHASE 1 — WIRE ONE NODE (reproduce-first):
  - Fill aef.yaml's five surfaces: objectives, tools.allow, policies, evaluator.suites,
    memory. Keep policies.require_hitl_above_risk at 0.0 until you deliberately raise it.
  - Identify the repo's existing entrypoint(s). Wrap vendor client construction behind an
    aef.providers.base.ModelProvider adapter (vendor SDK imports ONLY in providers/ or
    services/*/adapters/ — CI/AST rule). Convert one call site into a Node:
    (AEFState, Context, Services) -> tuple[StateDelta, Route], taking everything via Services.
    Declare deterministic:bool honestly (never True on a model/clock/RNG call) and
    side_effects; any non-pure node needs an idempotency_key_fn.
  - Wire it in aef_adapter.py. `aef run <module>` then `aef eval`/`aef trace` to prove it
    executes, scores, and replays.

PHASE 2 — GREEN BAR (must pass before any step is "done"):
    pytest -q
    mypy --strict <your_package>
    ruff check .
    ruff format --check <your_dirs>
  Write the test alongside the code, not after. Reproduce every bug with a failing test first.

PHASE 3 — BOUNDED SELF-IMPROVING LOOP:
  Start from a finite work-list (migration checklist items, a review's findings). For each:
  reproduce -> fix -> green bar -> ADR if it's a real behavior/contract change -> commit ->
  push to THIS repo's remote -> next. When the list is shipped, STOP. Do not invent new
  findings to keep running. "Self-learning" = writing reflections into memory (rule-based
  critic/judge first); it does NOT mean self-modification.

HARD-STOP GATES (pause and ask a human — do not proceed autonomously):
  1. Any push to a repo other than this one, or any external publish beyond `git push` here.
  2. Enabling aef/evolution/, weakening the deny-by-default PolicyEngine, or removing a HITL gate.
  3. Deleting or overwriting an existing user file (adopt/init are never-overwrite; keep them so).
  4. A breaking public-contract change you are not confident about.

Full protocol: aef-core docs/autonomy/self-improving-loop.md. Report per step what changed and
which test proves it. When the bounded list is done, stop and summarize.
```

---

See also: `self-improving-loop.md` (the full protocol this prompt enacts) and
`AGENT_INTEGRATION.md` at the aef-core repo root (the ingest-and-start guide).
