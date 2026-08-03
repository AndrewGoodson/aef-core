"""Graph-IR schema-compatibility gate: every JSON checkpoint under
`tests/fixtures/checkpoints/` must remain loadable through
`aef.state.load_state` forever. This directory only ever grows — when
`AEFState`'s schema changes, add a migration (`aef.state.migrations`),
bump `CURRENT_SCHEMA_VERSION`, and add a NEW fixture for the new version
rather than editing an existing one. CI runs this as its own step
(`.github/workflows/ci.yml`) so a schema change that silently breaks old
checkpoints fails the build, not just a downstream consumer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aef.state import AEFState, load_state
from aef.state.schema import CURRENT_SCHEMA_VERSION

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "checkpoints"


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def test_at_least_one_golden_fixture_exists() -> None:
    assert _fixture_files(), f"no golden checkpoint fixtures found under {FIXTURES_DIR}"


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=lambda p: p.stem)
def test_golden_checkpoint_still_loads(fixture_path: Path) -> None:
    raw = json.loads(fixture_path.read_text())
    state = load_state(raw)
    assert isinstance(state, AEFState)
    assert state.schema_version == CURRENT_SCHEMA_VERSION


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=lambda p: p.stem)
def test_golden_checkpoint_round_trips_after_load(fixture_path: Path) -> None:
    raw = json.loads(fixture_path.read_text())
    state = load_state(raw)
    reloaded = load_state(json.loads(state.model_dump_json()))
    assert reloaded == state
