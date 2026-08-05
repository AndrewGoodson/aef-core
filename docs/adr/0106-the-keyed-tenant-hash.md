# ADR 0106: The keyed tenant hash

## Status
Accepted. Closes trust case §2.3. **Keyed assignment is the default.**

## The weakness

`assigned_to_candidate` was a public deterministic function of a string the
tenant supplies. A tenant that controls its own tag can therefore compute
which arm any tag lands in and choose one — biasing exactly the evidence
promotion is read from. Demonstrated in the trust case:

```
tried 200 candidate tags at 99% exposure -> 1 lands on the incumbent: ['evader-106']
```

At lower exposures it is trivial.

## Decision

`blake2b(..., key=salt.material)` under an owner-held `CanarySalt`, loaded
from a file with the same discipline as the signing key — mode-checked,
minimum length, hidden from `repr`. **Not the signing key**: reusing one
secret for two purposes means a compromise of either leaks both, and the
release key is held by a person while this one is read by a running service.

`CanaryState` **refuses to construct** without a salt unless `unkeyed=True`
says so, and records `keyed` either way. The third instance of the same shape
in this repo — `SandboxPolicy` for network isolation, `ShadowRunner` for
containment, this for assignment: refuse unless the control is really there,
and make running without it something a caller states rather than inherits.

### What keying buys, precisely

It removes **offline** computation: a tenant without the salt cannot evaluate
the function at all, so it cannot sift candidate tags before using one. It
does **not** remove online probing — a tenant that can observe which arm it
landed in can still re-register under new tags until it lands where it wants.
That is one tag at a time and visible in whatever issues tenant tags, instead
of instant and invisible.

This bound is tested, not just written down. Calling it "unpredictable" would
be the overclaim this program has four ADRs about.

### Properties the key must not break, all measured

Monotone in exposure (the ladder accumulates evidence rather than reshuffling
it), stable per tenant, ~uniform at each stage within 3 points, and a new
version still reshuffles who is exposed. A different salt assigns a different
population — without which the key is decoration.

## What the adversarial round found

**The fingerprint was a cheap offline oracle.** `salt_fingerprint` is
persisted next to a rollout so a restart can prove it kept the same
population, which means it reaches state files and logs. It was a plain
`blake2b` of the salt — so guess a salt, hash it, compare, at microseconds per
guess.

**Any deterministic function of the salt is a verification oracle**, and that
is unavoidable if restarts are to prove anything. So the answer is to make
each guess cost: `pbkdf2_hmac` at 200k iterations, ~12ms measured, about 1000x
on an offline search and nothing on the once-per-rollout real use. Domain-
separated, so a fingerprint cannot be replayed as another digest of the same
salt. **It does not make a guessable salt safe** — it buys time against a weak
one, and the actual defence is that the salt is random, which is what
`CanarySalt.generate()` (`secrets`, not `random`) exists for.

**The same tenant, encoded two ways, got two arms.** `"café"` in NFC and NFD
are different byte sequences, so one tenant sending each from two clients
landed in different arms **52% of the time** — measured, not supposed. It sees
inconsistent behaviour *and* contributes samples to both arms, which is
precisely what stratifying by tenant exists to prevent. Tags are now
NFC-normalised before hashing; normalisation is not cosmetic here.

Checked and sound: the salt does not appear in a state `repr`, 0% exposes
nobody and 100% exposes everybody, two graph ids overlap at chance rather than
correlating, and an unkeyed rollout still serves while reporting
`keyed=False`.

## Consequences

Trust case §2.3's weakness is closed for offline search and **bounded, not
eliminated**, for online probing. A rollout that opts out is visibly unkeyed
rather than silently self-selectable.

**The recommendation is unchanged.** §2.3 was never one of the four reasons
carrying it — reason #1 is that criteria 1 and 6 have not run against the live
traffic and real tenants their own text names, and nothing here touches that.
An adopter with real tenants is still what is missing, and this ADR makes the
canary readier for one rather than substituting for it.

## Confidence
High on the mechanism: every property is measured, including the two defects
found by attacking it and the bound on what keying buys.

Moderate on the threat model. The attacker modelled is a tenant that controls
its own tag; a tenant that can also read the host's filesystem, or one
colluding with whoever issues tags, is out of scope and unaddressed.
