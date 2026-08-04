# ADR 0033: The autonomous self-improving loop is a versioned repo artifact, not a chat prompt

## Status
Accepted

## Context
aef-core has been developed largely via an autonomous hardening loop:
adversarial audit → reproduce → fix → verify → ADR → commit → repeat, run
self-paced with minimal human interaction (ADRs 0022–0032 were all produced
this way). Until now that protocol lived only in ephemeral session prompts.
Two problems with that:

1. **It is re-improvised every session.** The exact green bar, the
   reproduce-first rule, and — critically — the safety gates that make
   unattended running acceptable were restated by hand each time, with room
   to drift or be forgotten.
2. **Adopting repos inherit nothing.** The request that motivated this ADR
   is to make aef-core "ready to onboard new repo agents" that run the same
   self-improving loop. An onboarding agent needs the protocol *and its
   safety contract* as a durable, citable artifact, not tribal knowledge.

The autonomy is real and load-bearing, so it should be issued **from the
scaffold**, versioned and reviewable, the same way every other constraint
in this repo is.

## Decision
Added `docs/autonomy/self-improving-loop.md` as the canonical specification
of the loop. It fixes, in one versioned place: the loop shape, the four-
command green bar, the reproduce-first rule, the **HARD-STOP gates** (no
external publish / no push to other repos; no enabling `aef/evolution/`, no
weakening the PolicyEngine, no removing a HITL gate; never overwrite a user
file; stop on an unsure breaking change), the explicit boundary that
"self-learning" means reflection-into-memory and **not** self-modification
(evolution stays gated per ADR 0006/0010), the graph-engineering properties
unattended changes must not regress (each cited to its enforcing ADR), and
the requirement that every run works from a **bounded** work-list and stops
when it is done.

`aef adopt` emits a pointer to this spec into every adopted repo (see the
adopt-surface ADR and `AGENT_INTEGRATION.md`), so an adopted agent inherits
the same contract.

## Consequences
- The autonomy protocol is now reviewable, diffable, and versioned — a
  change to how unattended agents are allowed to operate is a reviewed
  commit, not an undocumented shift in prompt wording.
- The safety gates are stated once, authoritatively. An unattended agent
  (here or in an adopted repo) has a single source of truth for what it may
  do without a human and what it must stop for.
- No executable behavior changed in this ADR — it is documentation of an
  adopted practice plus the artifact that carries it. The green bar it
  specifies is the one already enforced by CI; the gates it names are
  already the project's operating rules. 296/296 tests, mypy --strict, ruff
  all remain green (this commit adds only docs).
- The evolution boundary is now written down as *the* thing that makes the
  autonomy safe, not an incidental constraint — reducing the risk that a
  future session reads "self-improving, run autonomously" and reaches for
  self-modification.

## Alternatives Considered
- **Encode the protocol as a CLI command (`aef loop`) that runs the cycle.**
  Rejected for now: the loop's steps (write a test, reason about a fix,
  author an ADR) are inherently model-driven, not a fixed script a CLI can
  execute; a command would either be a thin wrapper around "run the green
  bar" (already trivial) or would overclaim automation it can't deliver. A
  specification the agent follows is the honest artifact. `aef`-level
  tooling for the green bar can come later if it earns its keep.
- **Leave the protocol in session prompts.** Rejected: that is the status
  quo this ADR fixes — non-inheritable, drift-prone, and invisible to an
  onboarding agent.
- **Put the safety gates only in the emitted adopt files, not in aef-core.**
  Rejected: aef-core develops itself with this loop too, so the spec has to
  live here and be the source `adopt` copies a pointer to — one source of
  truth, not two that can diverge.

## Confidence
High — this records and versions a practice already in daily use (the ADR
trail is the evidence it works), and adds no executable behavior to get
wrong. The one judgment call — spec-the-agent-follows vs. a CLI that runs it
— is deliberately the conservative one, matching the repo's stance of not
building automation it can't honestly stand behind.
