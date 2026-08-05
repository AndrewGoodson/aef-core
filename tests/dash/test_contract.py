"""Milestone 1's acceptance tests.

The central claim is "a panel with no data cannot render green." That is a
claim about a type, so one of these tests runs `mypy` on a snippet and asserts
it is REJECTED — the property is that the compiler stops you, and a test that
only checked runtime behaviour would pass just as happily against a convention
somebody could forget.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import pytest

from aef.dash.contract import (
    FIELD_DISCLOSURE,
    FORBIDDEN_HTML_CONSTRUCTS,
    PANELS,
    Disclosure,
    DisclosureError,
    Known,
    Panel,
    PanelSpec,
    PanelState,
    Unknown,
    UnknownReason,
    disclosure_of,
    emittable,
    panel_spec,
)
from aef.harness.monitoring import Digest, evaluate_window

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# 1b — a panel with no data cannot render green.
# --------------------------------------------------------------------------


def test_unknown_has_no_state_attribute_at_all() -> None:
    """The structural half. There is no attribute to read, so there is no
    branch in which an empty panel produces HEALTHY."""
    unknown = Unknown(reason=UnknownReason.NO_LEDGER)
    assert not hasattr(unknown, "state")
    assert "state" not in vars(unknown)


def test_known_refuses_to_hold_the_unknown_state() -> None:
    with pytest.raises(ValueError, match="contradiction"):
        Known(value=1, state=PanelState.UNKNOWN)


def test_no_panel_and_no_reason_combination_renders_green() -> None:
    """Exhaustive over the actual product, not a sample. 10 panels x 13
    reasons — cheap enough to do properly, and the whole program's stated
    lesson is that a sampled check is the one that misses."""
    combinations = list(product(PANELS, UnknownReason))
    assert len(combinations) == len(PANELS) * len(UnknownReason)
    for spec, reason in combinations:
        panel = Panel(spec=spec, reading=Unknown(reason=reason))
        assert panel.state is PanelState.UNKNOWN, (spec.key, reason)
        assert panel.is_green is False, (spec.key, reason)


def test_known_panels_do_report_their_state() -> None:
    """The control for the test above: if Panel always returned UNKNOWN it
    would pass every assertion so far and be useless."""
    healthy = Panel(
        spec=panel_spec("acceptance"), reading=Known(value=0.5, state=PanelState.HEALTHY)
    )
    degraded = Panel(
        spec=panel_spec("acceptance"), reading=Known(value=0.0, state=PanelState.DEGRADED)
    )
    assert healthy.state is PanelState.HEALTHY
    assert healthy.is_green is True
    assert degraded.state is PanelState.DEGRADED
    assert degraded.is_green is False


def test_mypy_rejects_reading_state_without_narrowing() -> None:
    """The claim is that the TYPE stops you, so run the type checker.

    Asserting on runtime behaviour would prove only that today's code happens
    not to do it. This proves the next person cannot.
    """
    snippet = REPO_ROOT / "build" / "dash_narrowing_check.py"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(
        "from aef.dash.contract import Reading\n"
        "\n"
        "\n"
        "def is_green(reading: Reading[int]) -> bool:\n"
        "    return reading.state == 'healthy'\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--strict", str(snippet)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode != 0, (
            "mypy ACCEPTED an unnarrowed `.state` access on a Reading. The 'panel with no "
            f"data cannot render green' property is a convention, not a type.\n{result.stdout}"
        )
        assert "state" in result.stdout, result.stdout
    finally:
        snippet.unlink(missing_ok=True)


def test_mypy_accepts_the_narrowed_form() -> None:
    """The control. If the snippet above failed for an unrelated reason — a
    bad import, a syntax error — the test would pass while proving nothing."""
    snippet = REPO_ROOT / "build" / "dash_narrowing_ok.py"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(
        "from aef.dash.contract import Known, Reading\n"
        "\n"
        "\n"
        "def is_green(reading: Reading[int]) -> bool:\n"
        "    if isinstance(reading, Known):\n"
        "        return reading.state == 'healthy'\n"
        "    return False\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--strict", str(snippet)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, (
            f"the narrowed form should type-check; if it does not, the previous test's "
            f"failure proves nothing about narrowing.\n{result.stdout}"
        )
    finally:
        snippet.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# The three defects this milestone's adversarial round reproduced.
# Each is built from the REAL API, never a paraphrase of it.
# --------------------------------------------------------------------------


def test_a_real_digest_with_no_proposals_cannot_produce_a_green_panel() -> None:
    """The attack that defeated the module's central claim in four lines.

    Deliberately constructed from the actual `Digest`, not from a literal
    `None` — the point is that a real, shipped source in this repo hands you
    the value that broke it. Twice in the predecessor program a detector
    passed its own planted fault and was still wrong, both times because the
    fault was a paraphrase.
    """
    digest = Digest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert digest.acceptance_rate is None, "precondition: zero proposals means None"

    with pytest.raises(ValueError, match="Unknown case wearing an Optional"):
        Known(value=digest.acceptance_rate, state=PanelState.HEALTHY)


def test_known_optional_is_the_correct_spelling_and_it_works_both_ways() -> None:
    """Refusing None without offering the right spelling just relocates the
    mistake to `Known(value=x or 0, ...)`."""
    digest = Digest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    absent = Known.optional(
        digest.acceptance_rate,
        PanelState.HEALTHY,
        reason=UnknownReason.LEDGER_EMPTY,
    )
    assert isinstance(absent, Unknown)
    assert absent.reason is UnknownReason.LEDGER_EMPTY
    assert Panel(spec=panel_spec("acceptance"), reading=absent).is_green is False

    present = Known.optional(0.75, PanelState.HEALTHY, reason=UnknownReason.LEDGER_EMPTY)
    assert isinstance(present, Known)
    assert Panel(spec=panel_spec("acceptance"), reading=present).is_green is True


def test_the_other_optional_sources_are_the_same_trap() -> None:
    """Named in the error message, so they are named in a test. Each returns
    `X | None` where None means 'nothing to compare'."""
    digest = Digest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert digest.beating_manual_editing is None
    with pytest.raises(ValueError, match="Unknown case wearing an Optional"):
        Known(value=digest.beating_manual_editing, state=PanelState.HEALTHY)

    merged_at = datetime(2026, 1, 10, tzinfo=UTC)
    result = evaluate_window(
        [],
        baseline_pass_rate=0.9,
        merged_at=merged_at,
        now=merged_at,
    )
    assert result.observed_pass_rate is None
    with pytest.raises(ValueError, match="Unknown case wearing an Optional"):
        Known(value=result.observed_pass_rate, state=PanelState.HEALTHY)


def test_a_bare_string_state_is_refused_because_panelstate_is_a_strenum() -> None:
    """`PanelState` members ARE strings, so `state="unknown"` compared unequal
    to every member under `is` and slipped past the contradiction guard."""
    assert isinstance(PanelState.HEALTHY, str), "precondition: StrEnum"
    assert (PanelState.UNKNOWN == "unknown") is True
    # Bound to a name rather than written inline: ruff's F632 autofix rewrites
    # `"unknown" is PanelState.UNKNOWN` into `==`, which inverts the very gap
    # this line documents. A linter silently changing what an assertion proves
    # is worth the two extra characters.
    raw_state = "unknown"
    assert (raw_state is PanelState.UNKNOWN) is False, "precondition: the identity gap"

    with pytest.raises(TypeError, match="must be a PanelState"):
        Known(value=1, state="unknown")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be a PanelState"):
        Known(value=1, state="healthy")  # type: ignore[arg-type]


def test_an_arbitrary_object_with_a_state_attribute_cannot_be_a_reading() -> None:
    """Duck typing at a trust boundary: anything carrying `.state = HEALTHY`
    rendered green, because the else-branch trusted what it was handed."""

    @dataclass(frozen=True)
    class Impostor:
        state: PanelState = PanelState.HEALTHY

    with pytest.raises(TypeError, match="must be Unknown or Known"):
        Panel(spec=panel_spec("halt"), reading=Impostor())  # type: ignore[arg-type]


def test_an_empty_collection_is_still_data() -> None:
    """The boundary case, decided deliberately rather than by omission: empty
    is not absent. Zero recorded errors IS healthy, and refusing `[]` the way
    `None` is refused would force callers to report UNKNOWN for a question
    they can actually answer."""
    panel = Panel(spec=panel_spec("runs"), reading=Known(value=[], state=PanelState.HEALTHY))
    assert panel.is_green is True


# --------------------------------------------------------------------------
# 1a — every panel names what makes it UNKNOWN.
# --------------------------------------------------------------------------


def test_every_panel_declares_an_unknown_condition() -> None:
    for spec in PANELS:
        assert spec.unknown_when, spec.key


def test_a_panel_claiming_it_cannot_be_unknown_is_refused() -> None:
    with pytest.raises(ValueError, match="declares no UNKNOWN condition"):
        PanelSpec(key="wishful", title="Wishful", watches="nothing", unknown_when=())


def test_panel_keys_are_unique() -> None:
    keys = [spec.key for spec in PANELS]
    assert len(keys) == len(set(keys))


def test_unknown_reason_must_be_an_enum_member() -> None:
    """Free text here would defeat the routing the enum exists for."""
    with pytest.raises(TypeError, match="UnknownReason"):
        Unknown(reason="the ledger is missing I think")  # type: ignore[arg-type]


def test_panel_spec_lookup_names_the_alternatives() -> None:
    with pytest.raises(KeyError, match="known panels are"):
        panel_spec("no_such_panel")


# --------------------------------------------------------------------------
# 1d — no field is emitted whose disclosure nobody decided.
# --------------------------------------------------------------------------


def test_unregistered_field_raises_rather_than_defaulting() -> None:
    with pytest.raises(DisclosureError, match="no disclosure decision"):
        disclosure_of("some_field_added_next_tuesday")


def test_the_secrets_are_excluded() -> None:
    """Named explicitly. A test over the whole dict would pass if every entry
    were PUBLIC; these are the ones whose value is the point."""
    for field in (
        "signing_key",
        "canary_salt",
        "canary_salt_fingerprint",
        "api_key",
        "environment",
        "prompt_text",
        "response_text",
        "tool_arguments",
        "working_memory",
        "retrieved_context",
        "repo_root",
        "state_dir",
    ):
        assert disclosure_of(field) is Disclosure.EXCLUDED, field
        assert emittable(field) is False, field


def test_the_salt_fingerprint_is_excluded_and_the_salt_is_too() -> None:
    """ADR 0106 made the fingerprint a 200k-iteration PBKDF2 because it is an
    offline oracle against the salt. An export is a file that gets pasted
    around; putting the fingerprint in one hands over the oracle and the
    leisure to grind it."""
    assert disclosure_of("canary_salt_fingerprint") is Disclosure.EXCLUDED
    assert disclosure_of("canary_salt") is Disclosure.EXCLUDED
    # But the fact that keying is on is exactly what an operator must see.
    assert disclosure_of("canary_keyed") is Disclosure.PUBLIC


def test_error_message_is_redacted_but_its_shape_is_not() -> None:
    """The operator's question is "is it failing, and how" — answered by type
    and count. The message is the field most likely to stringify a connection
    URL or an echoed Authorization header."""
    assert disclosure_of("error_message") is Disclosure.REDACTED
    assert disclosure_of("error_type") is Disclosure.PUBLIC
    assert disclosure_of("error_count") is Disclosure.PUBLIC


def test_tenant_tags_are_redacted() -> None:
    """A tenant tag list in a shared file is a customer list."""
    assert disclosure_of("tenant_tag") is Disclosure.REDACTED
    assert disclosure_of("tenant_count") is Disclosure.PUBLIC


def test_every_registered_field_has_a_real_disclosure() -> None:
    for field, value in FIELD_DISCLOSURE.items():
        assert isinstance(value, Disclosure), field


# --------------------------------------------------------------------------
# 1c — read-only.
# --------------------------------------------------------------------------


def test_forbidden_constructs_cover_the_four_ways_to_get_a_write() -> None:
    """Not a spelling test: each of these is a distinct mechanism, and a list
    that covered only `<form>` would miss the three that matter more."""
    joined = " ".join(FORBIDDEN_HTML_CONSTRUCTS)
    assert "<form" in joined  # classic submit
    assert "<button" in joined  # scripted handler
    assert "fetch(" in joined  # background request
    assert "XMLHttpRequest" in joined  # the older background request
    assert "navigator.sendBeacon" in joined  # the one people forget
    assert "WebSocket" in joined  # the persistent one
