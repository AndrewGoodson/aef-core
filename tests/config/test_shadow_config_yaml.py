"""YAML 1.1's `off` is the boolean false, and the mode is spelled `off` (ADR 0173)."""

from __future__ import annotations

import pytest

from aef.config.schema import ShadowConfig


def test_a_bare_yaml_off_is_the_off_mode_not_a_type_error() -> None:
    # What `yaml.safe_load("containment: off")` hands the model.
    assert ShadowConfig(containment=False).containment == "off"  # type: ignore[arg-type]


def test_a_bare_yaml_on_is_refused_with_the_quoting_fix() -> None:
    with pytest.raises(ValueError, match="quote the mode"):
        ShadowConfig(containment=True)  # type: ignore[arg-type]


def test_the_quoted_and_bare_string_forms_still_validate() -> None:
    for mode in ("auto", "fallback", "off"):
        assert ShadowConfig(containment=mode).containment == mode
