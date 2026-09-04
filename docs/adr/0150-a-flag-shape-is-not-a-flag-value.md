# ADR 0150: A flag's shape is not a flag's value

## Status
Accepted. Fix found while running the adoption sequence end to end on
`main`; no increment asked for it.

## Context

ADR 0126 added `--strict-mcp-config --mcp-config {} --safe-mode` to
`ClaudeCodeProvider` so the operator's own MCP servers and global
`CLAUDE.md` stop reaching a node's model call — a seam hunt had measured
211,470 input tokens per call as issued against 4,684 isolated.

`--mcp-config {}` is **rejected by the CLI**. It validates the value against
a schema whose `mcpServers` key is required:

```
Error: Invalid MCP configuration:
mcpServers: Invalid input
```

So from the moment ADR 0126 landed, **every call through
`ClaudeCodeProvider` exited 1** — the whole no-API-key path of ADR 0112,
dead on `main` for hours, through four merges and a full green bar.

It shipped because the model quota was exhausted that day. Wave B was
explicitly instructed not to make live calls and to verify the flags from
`claude --help`, so its tests assert the *shape* of argv:

```python
assert argv[argv.index("--mcp-config") + 1] == "{}"
```

argv was perfectly well formed. **A shape assertion cannot tell a valid
flag value from an invalid one**, and no test in this repo had ever run the
binary.

Found by running `aef loop bootstrap --config` on a freshly adopted repo —
the documented first-day sequence — and reading the error.

## Decision

1. `_EMPTY_MCP_CONFIG = '{"mcpServers":{}}'` — one module constant, the
   smallest document the CLI's schema accepts. The unit test now **parses**
   the value and compares the object, so a malformed string fails there too.
2. `tests/providers/test_harness_live.py` runs the real binary, opt-in twice
   (CLI present **and** `AEF_LIVE_HARNESS=1`), mirroring
   `test_codex_live.py`. Both harness backends now have a live guard; only
   these two tests can catch a flag the CLI refuses.

## Evidence

```
--mcp-config {}                      Error: Invalid MCP configuration: mcpServers: Invalid input
--mcp-config {"mcpServers":{}}       is_error False, result "OK", input_tokens 2

mutations, restored from a shasum-verified backup:
  M1  revert to the shipped `{}`     unit 1 failed · LIVE 2 failed
  M2  drop the two MCP flags         LIVE 2 PASSED  — see below

which flag actually isolates (real CLI, same prompt):
  --strict-mcp-config --mcp-config {"mcpServers":{}} --safe-mode    input_tokens 2
  --safe-mode alone                                                 input_tokens 2
```

**M2 is a non-detection and it is correct.** `--safe-mode` alone achieves
the isolation, so removing the MCP flags changes nothing measurable — they
are belt-and-braces, not the mechanism. ADR 0126 introduced all three
together and attributed the 211,470 → 4,684 reduction to the MCP pair; that
attribution was never separated, and this measurement separates it:
**`--safe-mode` is the load-bearing flag.** The MCP flags are kept because
they are now correct, cost nothing, and hold if `--safe-mode`'s meaning
narrows — but nothing here rests on them.

## Consequences

- ADR 0126's isolation claim is true, for a different reason than it gave.
  An erratum there records both the broken value and the re-attribution.
- Two of this session's measurements were taken while the provider could
  not run: I11's judge A/B and I3's numbers predate ADR 0126 and are
  unaffected, but any live measurement attempted *after* it would have
  failed for this reason rather than for quota. Nothing was silently wrong;
  everything simply errored.
- The rule this generalises: **a test that asserts an argument's shape
  proves the caller's intent, not the callee's acceptance.** Where the
  callee is a separate binary, only running it closes that gap. Both
  harness providers now have exactly one live test each, and they are the
  only tests in this repo that spend quota.

## Confidence

High. The defect, the fix and the flag attribution were each measured
against the real CLI.
