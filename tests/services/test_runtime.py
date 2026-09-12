from __future__ import annotations

import pytest

from aef.kernel import CorruptedCheckpointError
from aef.services.runtime import _EphemeralDurability, agent_services
from aef.state import AEFState


def test_explicit_empty_judge_rubric_is_rejected_not_defaulted() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        agent_services(judge_rubric={})


def test_ephemeral_durability_refuses_inconsistent_cursor_pair() -> None:
    backend = _EphemeralDurability()
    state = AEFState(run_id="r1", agent_id="a1", objective="test")
    backend.save_checkpoint(state)
    with pytest.raises(CorruptedCheckpointError, match="cursor.*checkpoint"):
        backend.load_cursor("r1")
    backend.save_cursor("r1", "node_b")
    assert backend.load_cursor("r1") == "node_b"
    backend.save_checkpoint(state.model_copy(update={"checkpoint_seq": 1}))
    with pytest.raises(CorruptedCheckpointError, match="cursor.*checkpoint"):
        backend.load_cursor("r1")


def test_ephemeral_checkpoint_identity_is_immutable_with_identical_retries() -> None:
    backend = _EphemeralDurability()
    state = AEFState(run_id="r1", agent_id="a1", objective="test")
    backend.save_checkpoint(state)
    backend.save_cursor("r1", "node_b")
    backend.save_checkpoint(state.model_copy())
    with pytest.raises(CorruptedCheckpointError, match="immutable"):
        backend.save_checkpoint(state.model_copy(update={"objective": "changed"}))
    assert backend.load_latest("r1") == state
    assert backend.load_cursor("r1") == "node_b"
