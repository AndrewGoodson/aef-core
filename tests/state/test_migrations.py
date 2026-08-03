from datetime import UTC, datetime
from typing import Any

import pytest

from aef.state import (
    AEFState,
    MigrationCycleError,
    MigrationRegistry,
    NoMigrationPathError,
    load_state,
)
from aef.state.schema import CURRENT_SCHEMA_VERSION


def _v1_0_0_checkpoint() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "run_id": "r1",
        "agent_id": "a1",
        "objective": "test",
    }


def test_load_state_current_version_is_passthrough() -> None:
    state = load_state(_v1_0_0_checkpoint())
    assert isinstance(state, AEFState)
    assert state.schema_version == CURRENT_SCHEMA_VERSION


def test_missing_schema_version_defaults_to_pre_history() -> None:
    registry = MigrationRegistry()

    def upgrade(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "schema_version": "1.0.0"}

    registry.register("0.0.0", upgrade)
    raw = {"run_id": "r1", "agent_id": "a1", "objective": "x"}
    state = load_state(raw, registry=registry)
    assert state.schema_version == "1.0.0"


def test_migration_chain_applies_in_order() -> None:
    registry = MigrationRegistry()

    def v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
        raw = dict(raw)
        raw["schema_version"] = "0.1.0"
        raw.setdefault("objective", "backfilled")
        return raw

    def v1_to_current(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "schema_version": CURRENT_SCHEMA_VERSION}

    registry.register("0.0.0", v0_to_v1)
    registry.register("0.1.0", v1_to_current)

    raw = {"schema_version": "0.0.0", "run_id": "r1", "agent_id": "a1"}
    state = load_state(raw, registry=registry)
    assert state.objective == "backfilled"
    assert state.schema_version == CURRENT_SCHEMA_VERSION


def test_no_migration_path_raises() -> None:
    registry = MigrationRegistry()
    with pytest.raises(NoMigrationPathError):
        load_state(
            {"schema_version": "9.9.9", "run_id": "r", "agent_id": "a", "objective": "x"},
            registry=registry,
        )


def test_migration_cycle_detected() -> None:
    registry = MigrationRegistry()
    registry.register("0.0.0", lambda raw: {**raw, "schema_version": "0.0.0"})
    with pytest.raises(MigrationCycleError):
        load_state(
            {"schema_version": "0.0.0", "run_id": "r", "agent_id": "a", "objective": "x"},
            registry=registry,
        )


def test_duplicate_registration_rejected() -> None:
    registry = MigrationRegistry()
    registry.register("0.0.0", lambda raw: raw)
    with pytest.raises(ValueError):
        registry.register("0.0.0", lambda raw: raw)


def test_old_checkpoint_fixture_still_loads() -> None:
    """Golden-fixture guard: a real v1.0.0 checkpoint captured today must
    remain loadable forever. Extend this (never shrink it) as new schema
    versions ship — this is the local half of the CI schema-compat check."""
    old_checkpoint = {
        "schema_version": "1.0.0",
        "run_id": "golden-run-1",
        "agent_id": "golden-agent",
        "objective": "prove old checkpoints keep loading",
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "prov": {
                    "node_id": "n1",
                    "graph_version": "1.0.0",
                    "ts": datetime.now(UTC).isoformat(),
                    "trace_id": "t1",
                },
            }
        ],
        "checkpoint_seq": 3,
    }
    state = load_state(old_checkpoint)
    assert state.run_id == "golden-run-1"
    assert state.checkpoint_seq == 3
    assert state.messages[0].content == "hello"
