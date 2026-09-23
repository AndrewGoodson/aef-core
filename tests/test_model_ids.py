"""Every model ID this repo ships — in its example configs and in the
templates `aef adopt`/`aef init` write into other repos — must name a model
that exists. `claude-sonnet` was shipped for months; it is not an ID, and a
freshly adopted repo would have 404ed on its first call.

Kept deliberately narrow: this asserts the *shape* of a current ID, not a
table of current models, because a table here rots on every release. The
per-release check is `/new-model-check` (docs/adr/0111)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aef.cli.adopt import render_aef_yaml
from aef.cli.init import _render_config

REPO = Path(__file__).resolve().parents[1]
# A real current Anthropic ID: family, then a major version, e.g. claude-opus-5,
# claude-sonnet-4-6. No date suffix — the guide says never to append one.
CURRENT_ID = re.compile(r"^claude-(opus|sonnet|haiku|fable)-\d+(-\d+)?$")


def _model_lines(text: str) -> list[str]:
    values = []
    for line in text.splitlines():
        if "  model:" not in line:
            continue
        value = line.split(":", 1)[1]
        values.append(value.split("#", 1)[0].strip())  # drop a trailing YAML comment
    return values


@pytest.mark.parametrize(
    "path",
    sorted(REPO.glob("aef/config/agent.*.yaml")),
    ids=lambda p: p.name,
)
def test_example_configs_name_a_real_model(path: Path) -> None:
    models = _model_lines(path.read_text())
    assert models, f"{path.name} declares no model"
    for model in models:
        assert CURRENT_ID.match(model), f"{path.name}: {model!r} is not a model ID"


def test_adopt_template_names_a_real_model() -> None:
    for model in _model_lines(render_aef_yaml("repo")):
        assert CURRENT_ID.match(model), f"adopt template: {model!r} is not a model ID"


def test_init_template_names_a_real_model() -> None:
    for model in _model_lines(_render_config("agent")):
        assert CURRENT_ID.match(model), f"init template: {model!r} is not a model ID"


def test_every_shipped_default_names_the_same_model() -> None:
    """A model check moves the default in four places: two example configs
    and the two templates written into other repos. Half a migration is
    worse than none — an adopter's `aef init` and `aef adopt` would then
    disagree about which model they run. Pins agreement, not the value."""
    models = {
        *(m for p in REPO.glob("aef/config/agent.*.yaml") for m in _model_lines(p.read_text())),
        *_model_lines(render_aef_yaml("repo")),
        *_model_lines(_render_config("agent")),
    }
    assert len(models) == 1, f"shipped defaults disagree: {sorted(models)}"


def test_the_commented_effort_hint_is_valid_when_uncommented() -> None:
    """The templates show `effort` as a commented line so an adopter can find
    it (ADR 0212). A hint that fails validation once uncommented teaches the
    wrong key; this uncomments it and builds the config."""
    import yaml

    from aef.config.schema import ModelProviderConfig

    for text in (render_aef_yaml("repo"), _render_config("agent")):
        assert "  # effort: " in text
        doc = yaml.safe_load(text.replace("  # effort: ", "  effort: "))
        assert ModelProviderConfig(**doc["model_provider"]).effort is not None
