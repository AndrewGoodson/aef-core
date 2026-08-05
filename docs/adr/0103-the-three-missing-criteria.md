# ADR 0103: The three missing Phase-4 criteria

## Status
Accepted. Milestone 5. **All seven criteria are now implemented. Phase 4
remains disabled**, and that separation is the point: implementing the
criteria is the harness's job, deciding to trust them is the owner's.

## Built where, and why not in `aef/evolution/`

In `aef/harness/`, not in `aef/evolution/`. HARD-STOP #2 forbids enabling
evolution or weakening either disablement layer, and roadmap.md itself says
the owner-gated program "is not the Phase 4 evolution engine". Nothing here
touches `EvolutionConfig`; these are mechanisms the owner-gated promotion path
can use, and which Phase 4 *would* need if it were ever enabled.

## Criterion 1 — shadow execution

> The candidate runs alongside the incumbent on real input; only its
> DIVERGENCE is recorded; nothing it returns reaches a user.

**The part that cannot be paraphrased away:** running a candidate on live
input means its nodes actually execute. "Nothing it returns reaches a user"
says nothing about what it *does* on the way. A node declaring
`side_effects=EXTERNAL_CALL` makes that call, for real, twice — because the
incumbent made it too.

So `assert_shadowable` **refuses** any graph with a `MUTATING` node, at
construction rather than at the first live request. Suppression for everything
else is the existing `PolicyEngine` with an empty scope set — deny-by-default,
reused rather than reimplemented, because a bespoke "shadow mode" would be a
second security decision to keep in agreement with the first, and that is
exactly how the two service lists drifted (ADR 0091). HITL approvals are
**not** inherited: an approval the owner granted the incumbent is not an
approval for the candidate.

"Nothing it returns reaches a user" is enforced structurally.
`ShadowObservation` carries the incumbent's state and a `Divergence`; it has
no field holding the candidate's output, so there is no path by which a caller
can return it. A test asserts no attribute name even contains "candidate".

A candidate that raises is a divergence, not an outage — the incumbent has
already answered. Observing a candidate must never be more dangerous than not
observing it.

`divergence_rate` over zero observations **raises** rather than returning 0.0,
because "never ran" and "always agreed" are the same number otherwise, and the
second is the one that earns promotion.

## Criterion 6 — canary rollout

> stratified by tenant tag, gated on percentiles, previous version kept warm
> for rollback

Assignment is a hash of `(graph_id, version, tenant_tag)`: stable per tenant,
**monotone in exposure** (a tenant admitted at 5% is still admitted at 25%, so
advancing does not reshuffle the population and silently discard every sample
gathered), and reshuffled per version so the same tenants are not always the
guinea pigs. An empty tag is refused rather than defaulted, because defaulting
would silently exempt whoever forgot it and the exemption would look like a
passing canary.

Percentiles, not means, and nearest-rank rather than interpolated — an
operator asked to explain a rollback needs to point at a number that actually
happened. `warm_version` is carried in the state, because a rollback that has
to resolve its own target can fail at the moment it is needed.

**A tested, stated coverage limit.** p99 answers "99% are at or below this", so
a regression confined to the worst 1% sits entirely above it and no configured
percentile sees it. I found this because my first fixture used exactly 1% and
the gate passed it — that was not a fixture bug, it was the gate's coverage
showing. It is recorded as a test that asserts the limitation *and* asserts
that adding p100 catches it, rather than widened until green.

## Criterion 7 — signed release manifests

ADR 0087 named the hole precisely: the ledger is tamper-**evident**, not
signed, so a forger who rebuilds a consistent chain replays clean — every hash
is computed from data the forger also controls. A manifest binds what was
promoted, from what evidence, by whom, and when, under a key the thing being
judged never holds.

**HMAC-SHA256, and its limits are stated rather than implied.** It proves an
agent cannot forge an approval, which is the threat model here — the adversary
is the harness and the code it runs. It does **not** give third-party
verifiability: HMAC is symmetric, so anyone who can verify can also forge.
Ed25519 would fix that and needs a dependency the owner should decide on.
Saying "signed" while meaning "hashed" is what ADR 0087 already found; saying
it while meaning "MAC'd with a shared secret" would be the same mistake one
notch quieter.

The key loads from a file, not the environment: the sandbox scrubs the
environment to an allowlist, so a key living there would be one allowlist edit
away from reaching candidate code, and the edit would look like configuration.
A group/world-readable key file is refused — a key any local process can read
is not a key the harness is excluded from.

## What the adversarial round found

**A rolled-back candidate climbed the ladder again.** `rollback` reset the
stage index and nothing recorded that the rollout had failed, so the next
passing verdict sent the same candidate back up: advance → regress → rollback
→ advance, forever, re-exposing users on every lap. Reproduced. A rollback is
now terminal for that candidate — what comes next is a new version whose
evidence is about the fix.

**A manifest recording failed gates signed and verified cleanly.** The
artefact whose entire purpose is proving "promoted on this evidence" was
equally happy to prove a rejection had been approved. Reproduced. Promoting
over a failing gate now requires `override_reason`, which is itself in the
signed payload — an override is a legitimate owner act; an override nobody had
to type is an accident waiting to be cited later as intent.

Checked and sound: a signature does not replay across versions or onto altered
notes; suppression nulls no service the incumbent had (a shadow missing a
service would diverge for a harness reason and report it as a candidate
defect).

## Confidence
Moderate, and specifically lower than the last four milestones.

Every mechanism is real, tested behaviourally, and has a control alongside
each claim. But **none of the three has run against live traffic**, because
this repo has none. Shadow execution is tested with a synthetic incumbent and
candidate; the canary is tested against sample arrays, not against tenants.
The criteria say "against live traffic" and "stratified by tenant tag", and
what exists is a mechanism that would do those things correctly when connected
to something real. That gap is the single most important thing for the trust
case to state, and it is not one more test away — it needs an adopter with
traffic.
