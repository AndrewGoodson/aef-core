"""The three knowledge-layer knobs, reachable from `aef.yaml` (ADR 0193).

Until N2 measured the arms on the one-model corpus, `ContextConfig` carried
`impl` and `token_budget` and `build_retriever` passed `max_token_budget` —
so `knowledge_boost`, `staleness_half_life` and `knowledge_min_occurrences`
could be set only by hand-constructing `Services`. ADR 0184 reported that as
its defect 2 and could not fix it (no file under `aef/` was its to touch);
ADR 0193 fixes it, having measured a **+0.0470 task-metric delta** on this
repo's own corpus at `knowledge_boost=8.0` against the byte-identical-prompt
control — a configuration no adopter could express.

The load-bearing test here is not that the fields exist. It is
`test_the_shipped_defaults_are_the_measured_ones_and_there_is_one_copy_of_them`:
an unset knob must arrive at `MemoryRetriever` as the retriever's OWN default,
not as a literal repeated in the config layer. A measured default written down
twice is two numbers that must agree with nothing checking that they do.
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from aef.config.factory import build_retriever
from aef.config.schema import ContextConfig
from aef.services.context.memory_retriever import (
    DEFAULT_STALENESS_HALF_LIFE,
    MemoryRetriever,
)
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.in_memory import InMemoryMemoryStore


def _retriever(config: ContextConfig) -> MemoryRetriever:
    built = build_retriever(
        config,
        memory=InMemoryMemoryStore(),
        agent_id="a",
        knowledge=InMemoryKnowledgeStore(),
    )
    assert isinstance(built, MemoryRetriever)
    return built


def test_the_three_knobs_reach_the_retriever_from_the_config() -> None:
    built = _retriever(
        ContextConfig(
            impl="memory",
            token_budget=4000,
            knowledge_boost=8.0,
            staleness_half_life=2,
            knowledge_min_occurrences=3,
        )
    )
    assert built.knowledge_boost == 8.0
    assert built.staleness_half_life == 2
    assert built.knowledge_min_occurrences == 3
    assert built.max_token_budget == 4000


def test_the_shipped_defaults_are_the_measured_ones_and_there_is_one_copy_of_them() -> None:
    """An unset knob is the RETRIEVER's default, not a second literal.

    `knowledge_boost=0.0` is ADR 0110's I4 sweep (and ADR 0193's narrowing of
    what that null means); `staleness_half_life=5` is ADR 0116's. Both are
    asserted against `MemoryRetriever`'s dataclass fields rather than against
    numbers typed here, so `build_retriever` cannot acquire a private copy
    that drifts from the measurement.
    """
    fields = {f.name: f.default for f in dataclasses.fields(MemoryRetriever)}
    assert fields["knowledge_boost"] == 0.0
    assert fields["staleness_half_life"] == DEFAULT_STALENESS_HALF_LIFE == 5
    assert fields["knowledge_min_occurrences"] == 2

    built = _retriever(ContextConfig(impl="memory"))
    assert built.knowledge_boost == fields["knowledge_boost"]
    assert built.staleness_half_life == fields["staleness_half_life"]
    assert built.knowledge_min_occurrences == fields["knowledge_min_occurrences"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("knowledge_boost", -0.1, "non-negative"),
        ("staleness_half_life", -1, "non-negative"),
        ("knowledge_min_occurrences", 0, "at least 1"),
    ],
)
def test_an_invalid_knob_is_refused_at_config_load_time(
    field: str, value: float, message: str
) -> None:
    """The same refusals `MemoryRetriever.__post_init__` makes, one layer
    earlier — a config that loads clean must not construct an invalid runtime
    object at first use (`CommandProviderConfig`'s rule, ADR 0154)."""
    with pytest.raises(ValidationError) as excinfo:
        ContextConfig(impl="memory", **{field: value})
    assert message in str(excinfo.value)


def test_zero_disables_the_staleness_demotion_and_is_NOT_treated_as_unset() -> None:
    """`0` is a meaningful value for `staleness_half_life` — it turns the
    demotion off (ADR 0116) — so the "unset" sentinel has to be `None`. A
    falsy-check in `build_retriever` would silently restore the default 5 and
    an owner who disabled demotion would get it anyway."""
    assert _retriever(ContextConfig(impl="memory", staleness_half_life=0)).staleness_half_life == 0
    assert _retriever(ContextConfig(impl="memory", knowledge_boost=0.0)).knowledge_boost == 0.0
