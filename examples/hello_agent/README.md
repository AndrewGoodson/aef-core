# hello_agent

The minimal end-to-end example: three nodes (`draft` -> `search` ->
`summarize`), wired entirely to in-memory backends — no API key, no
network call, no external service.

Demonstrates, using only real (non-stubbed) Phase 0/1 components:

- The fixed node signature and `Services` dependency injection
  (`aef/kernel/contracts.py`)
- A `ModelProvider` call (`EchoModelProvider` — a demo stand-in, not a real
  adapter; swap in `aef.providers.anthropic_provider.AnthropicProvider` for
  a real model)
- A policy-gated tool call through `PolicyEngine` (`aef/security/tool.py`)
- Writing to `MemoryStore` (`aef/services/memory/in_memory.py`)
- Per-node OTel-shaped spans via `InMemoryTracer`
  (`aef/observability/in_memory.py`)
- Checkpointing via `InMemoryDurabilityBackend`
  (`aef/kernel/durability.py`)
- Scoring the finished run with `RuleBasedEvaluator`
  (`aef/services/eval/rule_based.py`)

## Run it

```bash
python -m examples.hello_agent.main
```

## Files

- `graph.py` — the graph definition, nodes, and the demo `ModelProvider`/`Tool`
- `main.py` — wires `Services` and runs it
