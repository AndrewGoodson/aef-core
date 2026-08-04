# ADR 0030: `Mem0Adapter.get()` no longer swallows genuine client failures as "not found"

## Status
Accepted

## Context
Broader sweep for bare/overly-broad exception handlers across `aef/`
(outside the gated `aef/evolution/`), per the standing methodology of
verifying real behavior rather than assuming a broad `except` is fine.
Found three `except Exception`/bare-`except` sites total:

- `aef/cli/main.py`'s top-level handler — intentional and correct: the
  CLI's own last-resort formatter, converts any exception to a readable
  `error: {exc}` message instead of a traceback.
- `aef/kernel/executor.py`'s `fallback_node_id` handler — intentional and
  correct: a node explicitly opts into "any failure of mine routes to my
  declared fallback," which is exactly this repo's own fallback-provider
  design pattern applied to nodes.
- `aef/services/memory/adapters/mem0_adapter.py`'s `Mem0Adapter.get()` —
  the one real bug. `except Exception: return None` wrapped
  `self._client.get(native_id)`, silently converting *any* failure into
  "record not found."

Checked what this was actually protecting against by reading the real
`mem0.Memory.get()` source (not assumed): it calls
`self.vector_store.get(vector_id=memory_id)`, checks `if not memory:
return None`, and returns `None` cleanly — it **never raises** for a
not-found id. `Mem0Adapter.get()` already has its own `if not hit: return
None` check immediately after the client call, which is what actually
handles the legitimate not-found case. The `except Exception` wrapper
therefore caught nothing a not-found lookup would ever trigger — it only
ever intercepted genuine failures: a downed vector store, an internal
mem0/faiss/qdrant bug, a malformed native id causing an unrelated crash
deep inside mem0's own code. All of those were silently converted into
the exact same `None` a caller gets for "this memory legitimately doesn't
exist" — indistinguishable, with no way for a caller checking `if
store.get(id) is None:` to tell the difference. This is the same
silently-swallowed-failure pattern this session has fixed repeatedly
(ADR 0022/0025/0026), here in the one place it hadn't yet been checked.

No existing test exercised this path — nothing made the fake client's
`.get()` raise, so this was untested defensive code doing the wrong
thing, not a deliberately-tested design choice.

## Decision
Removed the `try`/`except` entirely. `self._client.get(native_id)` is now
called directly; any exception it raises propagates to the caller,
exactly like every other `self._client.*` call in this same adapter
(`write()`'s `add()` call and `query()`'s `search()` call both already
let exceptions propagate — `get()` was the one inconsistent case). The
`if not hit: return None` check (unchanged) still correctly handles the
real not-found case.

## Consequences
- A genuine backend failure during `get()` now surfaces as a real
  exception instead of a value indistinguishable from "not found" —
  callers can now actually distinguish "this memory was never written"
  from "the memory backend is broken right now."
- No behavior change for the legitimate not-found case (still `None`,
  still via the existing `if not hit` check) or the never-written-id
  short-circuit (unchanged, still returns `None` without calling the
  client at all).
- 288/288 tests (up from 287/287; one new test using a fake client whose
  `.get()` raises, asserting the exception propagates rather than being
  swallowed), mypy --strict clean, ruff clean.
- The other two `except Exception` sites in the codebase (CLI top-level
  handler, executor's fallback-node handler) were reviewed in the same
  pass and confirmed correct as-is — no changes needed there.

## Alternatives Considered
- **Catch a narrower, mem0-specific exception type instead of removing
  the try/except entirely.** Rejected: there's no evidence any exception
  type from `.get()` should be treated as "not found" — the real SDK's
  own not-found path never raises at all, so there's nothing left for a
  narrower catch to usefully catch. If a future mem0 version changes this
  contract, that's a reason to add a specific, justified catch then, not
  to keep a speculative broad one now.

## Confidence
High — the actual `mem0.Memory.get()` behavior was confirmed by reading
its real source (not assumed or inferred), the fix was verified to still
correctly return `None` for genuine not-found and never-written-id cases
while now propagating a genuine failure, and the broader sweep confirmed
the other two `except Exception` sites in the non-gated codebase are
correct by design rather than needing the same fix.
