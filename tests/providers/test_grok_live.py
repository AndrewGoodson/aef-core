"""The Grok path, run against the real CLI (ADR 0154).

Every flag and every field name in `GrokProvider` came from running
`grok 1.0.5` rather than from reading `grok --help` and hoping. That was not
optional. Grok's headless door is `-p/--single <PROMPT>`, where the prompt is
the *flag's value* — guess `claude`'s trailing-positional shape and you get an
interactive TUI that hangs rather than an error. Its reply lives in `text`,
not Claude's `result`; its stop reason in `stopReason`, not `stop_reason`.
Each of those wrong guesses produces an empty completion and no exception.

Opt-in twice — the CLI must exist AND `AEF_LIVE_HARNESS` must be set —
because it spends the operator's Grok quota. Same contract as
`test_harness_live.py` and `test_codex_live.py`; ADR 0150's rule is that
every adapter to an external binary ships with one of these and the author
runs it.

    AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_grok_live.py
"""

from __future__ import annotations

import os
import shutil

import pytest

from aef.providers.base import CompletionRequest, ProviderMessage
from aef.providers.harness_provider import GrokProvider

needs_grok = pytest.mark.skipif(
    not shutil.which("grok") or not os.environ.get("AEF_LIVE_HARNESS"),
    reason="needs the grok CLI and AEF_LIVE_HARNESS=1 (spends quota)",
)

# `grok models` on 2026-09-04 lists `grok-4.6` (default) and `grok-4.5`.
# NOT `grok-4.6-build` — that is the name `modelUsage` reports back, and
# `-m grok-4.6-build` exits 1 with `Invalid params: "unknown model id"`.
LIVE_MODEL = "grok-4.6"


@needs_grok
def test_grok_answers_through_the_provider() -> None:
    """Every flag the adapter passes, judged by the binary rather than by a
    string comparison — and every field it reads, judged by the payload."""
    result = GrokProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(
                ProviderMessage(role="system", content="Answer with exactly one word."),
                ProviderMessage(role="user", content="Reply with the single word OK"),
            ),
            model=LIVE_MODEL,
            max_tokens=200,
        )
    )
    assert result.content.strip() == "OK"
    assert result.stop_reason == "end_turn"
    # Zero here would mean `usage` was not found and the call quietly
    # reported free — the failure mode `test_codex_live.py` guards too.
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    # From `modelUsage`, so the SERVER's name for what answered, which is
    # deliberately not the id `-m` accepts.
    assert result.model.startswith("grok-4.6")


@needs_grok
def test_the_projects_instructions_do_not_reach_the_call() -> None:
    """Grok discovers project instructions exactly the way Claude Code does —
    `grok inspect` in this repo lists `Claude.md` (~3,369 tokens), `Agents.md`
    (~1,784) and 78 skills — and has **no `--safe-mode`**. `--cwd <empty dir>`
    is the only lever, and this is the test that says whether it still works.

    Measured 2026-09-04, same prompt, same box (ADR 0154):

        arm                              uncached  cached  TOTAL IN
        baseline, repo cwd, no flags       24,001       0    24,001
        tool flags only                    18,272   5,248    23,520
        --cwd <empty dir> only             12,821   5,760    18,581
        both (what this adapter sends)     12,688   5,248    17,936

    **This test is only worth its quota because it was mutation-checked, and
    the first version failed that check.** Written against Grok's raw
    `usage.input_tokens`, it PASSED with `--cwd` removed from the provider:
    that field is the uncached remainder, and on a warm cache an unisolated
    call reports less of it than a cold isolated one. `GrokProvider` now
    reports the total context, which is the only column above that separates
    the arms, and the same mutation then fails here as it should.

    The bound is 20,000, not 5,000, and that is the honest number: the
    operator's GLOBAL `~/.claude/Claude.md` still reaches the call — the
    isolated run's own `thought` field quoted a rule that exists only there —
    and Grok 1.0.5 offers no flag that stops it. Claude's `--safe-mode` gets
    that call to 2 input tokens; this is what Grok can do, stated as such
    rather than dressed up.
    """
    result = GrokProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content="Reply with the single word OK"),),
            model=LIVE_MODEL,
            max_tokens=200,
        )
    )
    assert result.input_tokens < 20_000, (
        f"{result.input_tokens} input tokens: --cwd is no longer isolating this repo's "
        f"CLAUDE.md/AGENTS.md from the call (24,001 unisolated when measured)"
    )
