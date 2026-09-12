# Graph engineering and evidence-based learning

The [public showcase](https://andrewgoodson.github.io/aef-core-site/) explains
AEF's graph contract, controlled tools, repository integration and learning
protocol. Its source lives in [`site/`](../site/README.md). It is a static
explanation and command preview; visiting it does not run an agent.

## Engineering methods and implementation

| Method | AEF implementation | Boundary |
| --- | --- | --- |
| Explicit graph execution | [`GraphExecutor`](../aef/kernel/executor.py), fixed node contracts, injected services | Model nodes remain nondeterministic; execution is not a guarantee of correct reasoning. |
| Durable state and replay | [`durability.py`](../aef/kernel/durability.py), [`replay.py`](../aef/kernel/replay.py) | Re-executing deterministic nodes checks consistency, not task quality. |
| Controlled tool access | [`PolicyEngine`](../aef/security/tool.py), human approval and audit | Target code must route tools through the policy service. Scaffold files alone do not enforce containment. |
| Context and consolidation | [`memory_retriever.py`](../aef/services/context/memory_retriever.py), [`consolidate.py`](../aef/services/knowledge/consolidate.py) | Memory is fallible data. Persistence depends on configured services; this is not a knowledge graph. |
| Outcome reflection | [`rule_based_reflection.py`](../aef/reasoning/rule_based_reflection.py), [`llm_reflection.py`](../aef/reasoning/llm_reflection.py) | LLM reflection is off by default. Existing trials have not demonstrated task improvement. |
| Evaluated prompt proposals | [`prompt_proposer.py`](../aef/harness/prompt_proposer.py), [`loop.py`](../aef/harness/loop.py) | Bounded proposals and gates exist. Passing gates escalates to a human; auto-merge and evolution remain disabled. |

The generated native persona graph follows `retrieve → prompt_agent → reflect
→ consolidate → END`. Custom graphs and domain evaluations still require
explicit integration. Only Knowledge, Policies, Tools, Objectives and
Evaluation Metrics vary per agent.

## Reusable learning instructions

[`site/learning-protocol.txt`](../site/learning-protocol.txt) is a portable
template derived from the evidence protocol in [`AGENTS.md`](../AGENTS.md).
Fill in its objective, target, permitted changes, acceptance checks and budget.
Use it alongside the target owner's instructions, never as a replacement.

The protocol requires observed failures, pinned conditions, bounded candidate
lessons, counterexamples, regression checks and reviewed results. Prompt-quality
claims require matched evaluation with held-out tasks and cost reporting;
placebo controls help distinguish useful advice from unrelated variation.
Neither a critique nor a passing software test proves learning improved.

The negative result stays visible: [ADR 0204](adr/0204-the-loop-on-a-repo-somebody-uses-and-the-bullet-that-made-it-worse.md)
records a limited owner-repository trial scoring incumbent **0.67**, learned
lesson **0.40**, and placebo **0.87**. This is evidence against adopting that
lesson, not a general framework ranking. AEF's learning quality remains unproven.

## Research context

Primary sources checked September 12, 2026. These methods help explain design
choices and possible experiments; citing them does not mean AEF implements
their algorithms or inherits their reported results.

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence):
  checkpointed graph state and thread-scoped continuity. AEF implements its own
  kernel and durability layer; it does not require LangGraph.
- [Reflexion](https://arxiv.org/abs/2303.11366): linguistic feedback retained for
  later attempts. AEF has reflection and memory components, but its task gains
  need independent measurement.
- [Self-Refine](https://arxiv.org/abs/2303.17651): iterative feedback and revision.
  AEF's reflection interfaces are related building blocks, not a claim that
  this paper's full procedure runs automatically.
- [GEPA](https://arxiv.org/abs/2507.19457): reflective prompt search using execution
  feedback and a Pareto frontier. This is a research direction, **not implemented
  in AEF**. The offline optimizer remains a stub.

The [roadmap](roadmap.md) and source remain authoritative for capability
boundaries. No “best framework,” “top methodology” or performance superiority
claim is supported by this showcase.
