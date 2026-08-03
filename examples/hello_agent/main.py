"""Run the hello_agent example end-to-end, entirely in-memory:

python -m examples.hello_agent.main
"""

from __future__ import annotations

import uuid

from aef.kernel import GraphExecutor, InMemoryDurabilityBackend, Services
from aef.observability.in_memory import InMemoryTracer
from aef.security.tool import PolicyConfig, PolicyEngine
from aef.services.eval.rule_based import RuleBasedEvaluator
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState
from examples.hello_agent.graph import EchoModelProvider, build_graph


def main() -> None:
    services = Services(
        model_provider=EchoModelProvider(),
        memory=InMemoryMemoryStore(),
        tracer=InMemoryTracer(),
        durability=InMemoryDurabilityBackend(),
        policy_engine=PolicyEngine(PolicyConfig(allowed_scopes=frozenset({"web_search_ro"}))),
    )

    initial_state = AEFState(
        run_id=str(uuid.uuid4()),
        agent_id="hello-agent",
        objective="Find out what AEF stands for.",
    )

    executor = GraphExecutor(build_graph().compile(), services)
    result = executor.run(initial_state, record_trace=True)
    final_state = result.final_state

    print("=== final messages ===")
    for message in final_state.messages:
        print(f"[{message.role}] {message.content}")

    print("\n=== tool results ===")
    for tool_result in final_state.tool_results:
        print(tool_result)

    print("\n=== plan ===")
    print(final_state.plan)

    record = RuleBasedEvaluator().evaluate(final_state)
    print("\n=== evaluation ===")
    print(
        f"task_completion={record.task_completion}  passed={record.passed}  "
        f"cost_tokens={record.cost_tokens}"
    )

    tracer = services.tracer
    assert isinstance(tracer, InMemoryTracer)
    print(f"\n=== spans emitted: {len(tracer.spans)} ===")
    for span in tracer.spans:
        print(f"  {span.name}")


if __name__ == "__main__":
    main()
