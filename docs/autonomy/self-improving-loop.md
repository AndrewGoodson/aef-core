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
  replayable). LLM-backed reflection is implemented with bias controls
  (ADR 0115), but stays off by default. Its measured limits and later
  evaluations are recorded in `docs/roadmap.md`; implementation alone does
  not establish better lessons or task outcomes.
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

## 9. Unattended-run prompt blocks (from the vendor migration guide)

Added by `/new-model-check` on 2026-09-03 against `claude-fable-5-1`, from
the bundled `claude-api` skill's `shared/model-migration.md` (Claude Code
2.1.258). The guide's finding: a capable long-horizon model still stops to
*describe* the next step or ask permission for one the request already
covered, and a person has to type "continue". The two blocks below
mitigated that; the guide says apply both unless context is tight, and that
the opening sentence of the first is load-bearing. It also says to **keep**
any existing instruction to test or check work before reporting — §2 and
§3 stay. Re-run `/new-model-check` when the model changes; these blocks are
model-dated and this section is where the next run edits.

> You are operating autonomously. The user is not watching in real time and cannot answer questions mid-task, so asking 'Want me to...?' or 'Shall I...?' will block the work. For reversible actions that follow from the original request, proceed without asking. Stop only for destructive actions or genuine scope changes the user must decide. Offering follow-ups after the task is done is fine; asking permission before doing the work is not.
>
> Exception: when the user is describing a problem, asking a question, or thinking out loud rather than requesting a change, the deliverable is your assessment. Report your findings and stop. Don't apply a fix until they ask for one.
>
> Before ending your turn, check your last paragraph. If it is a plan, an analysis, a question, a list of next steps, or a promise about work you have not done ('I'll...', 'let me know when...'), do that work now with tool calls. That includes retrying after errors and gathering missing information yourself. Do not stop because the context or session is long. End your turn only when the task is complete or you are blocked on input only the user can provide.
>
> Before running a command that changes system state (such as restarts, deletes, or config edits), check that the evidence actually supports that specific action. A signal that pattern-matches to a known failure may have a different cause.

The stops this repo adds to "destructive actions or genuine scope changes"
are exactly the HARD-STOP gates in §4.

> \# Delivering work
> The user's request - or the plan they approved - sets the scope, and the scope is the deliverable: don't quietly narrow, widen, or swap it. Read ambiguity the way a careful colleague would: make routine judgment calls yourself, and check in only when different readings would lead to materially different work. If you see a real problem with the task as specified, say so in a sentence or two and keep building under stated assumptions; if the user hears the concern and reaffirms, that is their decision, so deliver the full request.
>
> If a question comes up partway, first do everything that doesn't depend on the answer; then state the assumption you made, or - when going ahead on a wrong guess would be unsafe or would make the work useless - put the question at the end of a turn that also delivers that progress. If one part turns out to be blocked, complete every other part in full and say exactly what you left out and why - the whole task is the deliverable, and scaling it down is the user's call, not yours. A step you have decided on is something to run, not to announce: describing the next step and ending the turn leaves it undone until the user replies.
>
> Keep changes to what the request needs. Something else you notice worth doing - cleanup or documentation the task didn't call for, a change to a file the task didn't require - is a suggestion to make at the end, not a change to make; actions clearly beyond what the ask implies, and risky or destructive ones, still need the user's go-ahead.

Scope and test coverage — the guide saw far fewer unrequested additions and
much less committed scratch-test code with no change in task success:

> If, while working or testing, you find a pre-existing bug, a performance concern, or behavior the task doesn't mention, don't fix, optimize or extend it in this change unless the requested behavior cannot work without it; report it as a follow-up in your summary. Where the task is ambiguous, implement the reading its wording and the surrounding code most directly support, state that assumption in your summary, and don't build for the other readings as well. Verify your work however you like; scratch scripts and quick checks need not be kept. Commit tests only where the task asks for them or this repository already keeps tests for this kind of change, sized like the neighboring test files - roughly one focused test per stated behavior - and don't turn scratch checks into additional permanent test files. This is about extras only: implement every behavior the task asks for, completely.

Targeted edits — the model is more likely than its predecessor to rewrite a
whole file where a small edit would do:

> The number of tokens used to edit files is best minimized, all else being equal. Therefore, when it will not affect the end result, try to surgically edit a file rather than rewrite the entire thing.
