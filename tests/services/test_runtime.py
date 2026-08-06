from __future__ import annotations

import pytest

from aef.services.runtime import agent_services


def test_explicit_empty_judge_rubric_is_rejected_not_defaulted() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        agent_services(judge_rubric={})
