# The AEF self-improving loop — autonomy protocol

This is the **canonical, versioned specification** of the autonomous
hardening / self-improving loop that aef-core is developed with and that
adopting repos inherit. It exists as a repo artifact — not a chat prompt —
so the same contract is *issued from the scaffold* every time, rather than
re-improvised per session. `aef adopt` emits a short pointer to this file
into every adopted repo (see `AGENT_INTEGRATION.md`).

Status: **adopted project practice** (see docs/adr/0033). Applies to any
coding agent — Claude, Codex, Cursor, GitHub Copilot, or other — doing
unattended work in this repo or a repo that adopted aef-core. The protocol is
harness-agnostic; only the file the agent reads to find it differs (see the
harness table in `AGENT_INTEGRATION.md`).

---

## 1. What the loop is

A bounded, self-paced cycle:

```
audit (adversarial construction)
  -> reproduce the defect with a failing test / real command
    -> fix
      -> verify (the green bar, below)
        -> ADR if it is a real behavior/contract change
          -> commit + push
            -> next item, until a BOUNDED work-list is done
```

It is a *workflow*, not an agent (Anthropic's sense): control flow is fixed
here, in the protocol; only the individual fixes are model-decided. That is
deliberate — it is the same two-plane determinism the kernel enforces
(constraint #1/#2), applied to the development process itself.

## 2. The green bar (every step, all four must pass)

```
pytest -q
mypy --strict aef
ruff check .
ruff format --check aef tests
```

A step is not "done" until all four are green. Test count must grow or hold,
never silently shrink.

## 3. The reproduce-first rule

Never write a fix before a test (or a real, logged command) that
*reproduces the defect and fails the way it was reported*. Every ADR from
0022 onward was found this way: hand-build the adversarial input, run real
code (a real SDK, a real file, a real graph) against it, watch it fail,
then fix, then watch it pass. A pure code-read has never found what
adversarial construction found. This is the single most load-bearing rule
in the protocol.

## 4. HARD-STOP gates (the only things that require a human)

Unattended running is only acceptable because these are gated. Pause and
ask a human — do **not** proceed autonomously — for any of:

1. **Any push to a repo other than the current one, or any external
   publish** (package upload, posting to a service, sending data off-box)
   beyond `git push origin main` on this repo.
2. **Enabling `aef/evolution/`**, weakening the deny-by-default
   `PolicyEngine`, or removing/loosening a HITL approval gate.
3. **Deleting or overwriting an existing user file** in an adopted target
   repo. `aef adopt`/`aef init` are never-overwrite; keep them so.
4. **A genuine breaking-behavior change you are not confident about** — when
   in doubt on a public contract, stop and ask.

Everything else: decide and proceed. The gates are narrow on purpose — they
cover the irreversible and the outward-facing, nothing else.

## 5. What "self-learning" means here (and what it does NOT)

- **In scope:** writing reflections/critiques into memory so lessons persist
  across runs — the rule-based critic/judge slice scoped in
  `docs/design/phase3-reflection-critic-judge-brainstorm.md` (grounded in
  already-recorded signals: tool errors, eval failures; deterministic;
  replayable). LLM-judge reflection is a planned *later* slice, with the
  known bias mitigations (position/verbosity/self-preference).
- **Out of scope, permanently gated:** self-modification. `aef/evolution/`
  is disabled in code (ADR 0006/0010) and stays that way. The loop improves
  the *codebase* via reviewed commits, never rewrites *itself* at runtime.
  This boundary is what makes unattended autonomy safe rather than reckless.

## 6. Graph-engineering baseline the loop holds the line on

Unattended changes must not regress these established properties. Each is
enforced by tests and recorded in an ADR:

| Property | Enforced by | ADR |
|---|---|---|
| Two-plane determinism (pure kernel, quarantined LLM nodes) | node contract + replay | constraint #1/#2 |
| Replay re-executes deterministic nodes, trusts recorded non-det output | `ReplayEngine`; trace-chain validation | 0023 |
| Atomic durability writes + recovery past a torn checkpoint | `_atomic_write_text`; `load_latest` fallback | 0031 |
| HITL pause is always resumable; resume is at-least-once | checkpoint-before-raise; idempotency-key contract | 0032, 0010 |
| Deny-by-default security; positive-risk → REQUIRE_HITL | `PolicyEngine` | constraint #6 |
| Vendor SDK isolation (providers/ + services/*/adapters/ only) | AST scan in CI | constraint #3 |
| Fan-out typed but deferred; checkpoint format carries `schema_version` | `Route` type; `AEFState.schema_version` + migrations | 0007, 0031 |

When fan-out is eventually executed, it forces multiple pending cursors /
pending-writes-style partial-superstep persistence — version `cursor.json`
at that point (it is the one unversioned on-disk artifact today).

## 7. Bounded, not open-ended

"Autonomous until done" requires a *done*. Every loop run starts from an
explicit, finite work-list (a review's findings, a queued task list). When
the list is shipped, **stop** — do not manufacture new findings to keep
running. A fresh audit is a new, deliberately-started loop, not an implicit
continuation. Unbounded self-running with push access is exactly the shape
the HARD-STOP gates and this bound exist to contain.

## 8. Per-step checklist (copy into a todo per work item)

- [ ] Reproduce: failing test / real command that fails as reported
- [ ] Fix
- [ ] Green bar: pytest -q · mypy --strict aef · ruff check . · ruff format --check aef tests
- [ ] ADR (Nygard format) if real behavior/contract change; update docs/adr/README.md
- [ ] Commit (conventional prefix, correct co-author trailer) + push origin main
- [ ] No HARD-STOP gate crossed (if one is, stop and ask instead)
