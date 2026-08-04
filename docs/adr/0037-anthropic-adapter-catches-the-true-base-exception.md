# ADR 0037: `AnthropicProvider` catches `anthropic.AnthropicError`, not just `APIError`

## Status
Accepted

## Context
Round-1 line-by-line providers audit found a vendor-exception leak (rated
High). `AnthropicProvider.complete` wrapped only `except anthropic.APIError`.
But the `anthropic` SDK (v0.120.2) has `AnthropicError` subclasses that are
**not** `APIError` and can surface from `messages.create()` —
`WorkloadIdentityError` (raised in the auth/credentials token-fetch path) and
`RetryableError` (bare `raise` on retry exhaustion). Confirmed directly:
`issubclass(anthropic.WorkloadIdentityError, anthropic.APIError)` is `False`
while `issubclass(..., anthropic.AnthropicError)` is `True`.

Two problems, both reproduced:
1. Those exceptions leaked past the adapter as raw vendor types, violating
   this module's own contract (`base.py`: "adapters must not let
   vendor-specific exception types leak past their own module") — the whole
   point of the provider layer and constraint #3's vendor isolation.
2. Worse: `FallbackProvider.complete` only catches `ModelProviderError`, so a
   leaked raw vendor exception from the primary provider **aborts the entire
   fallback chain** instead of falling through to a healthy provider.
   Reproduced end-to-end: a `FallbackProvider([anthropic_that_raises_
   WorkloadIdentityError, healthy_provider])` raised the raw
   `WorkloadIdentityError` instead of returning the healthy provider's result.

## Decision
The adapter now catches `anthropic.AnthropicError` — the true base of every
exception the SDK raises — and wraps it in `ModelProviderError`
(`from exc` to preserve the cause). No anthropic exception can now escape the
adapter as a raw vendor type.

## Consequences
- Any anthropic failure (auth, rate limit, network, retry exhaustion,
  credentials) now surfaces as `ModelProviderError`, so `FallbackProvider`
  correctly falls through to the next provider. Reproduced: the fallback now
  returns the healthy provider's result instead of aborting.
- Constraint #3 (vendor isolation) is honored at the *exception* boundary,
  not just the import boundary — a leaked exception type is a vendor detail
  escaping `providers/` just as surely as a leaked import would.
- 305/305 tests (two new: adapter wraps a non-APIError AnthropicError, and
  FallbackProvider recovers when the primary raises one), mypy --strict
  clean, ruff clean.

## Alternatives Considered
- **Enumerate the specific non-APIError subclasses
  (`WorkloadIdentityError`, `RetryableError`, ...) alongside `APIError`.**
  Rejected: brittle — a future SDK version could add another
  `AnthropicError` subclass and reintroduce the leak. Catching the documented
  base is correct and future-proof; there is no anthropic exception that
  should escape this adapter unwrapped.
- **Catch `Exception`.** Rejected: too broad — a genuine bug in the adapter's
  own translation code (e.g. an `AttributeError` on a malformed response)
  should not be relabeled a provider failure and silently trigger fallback;
  only *vendor* exceptions should. `AnthropicError` is exactly that set.

## Confidence
High — the exception hierarchy was confirmed by direct `issubclass` checks
(not assumed), both the raw leak and the FallbackProvider-abort were
reproduced before the fix, and catching the vendor's own documented base
exception is the correct, minimal, future-proof boundary.
