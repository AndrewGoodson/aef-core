"""A16 — a balanced marker pair in the adopter's own prose.

Reproduced (ADR 0172, R2). This one has no attacker either, and it is worse
for it: **the scaffold's own onboarding kit teaches adopters the literal
marker strings**, so an adopter who documents them — or quotes them in a code
fence explaining what `aef adopt` does — writes a balanced
`<!-- aef:begin -->` … `<!-- aef:end -->` pair into their `CLAUDE.md`. Adopt
found the pair, decided it was its own block, and REPLACED the text between
it. Measured:

    grep -c "RULE 7" CLAUDE.md  ->  0

with the CLI printing *your bytes outside it are unchanged*. ADR 0153's three
refusals covered the UNBALANCED shapes; the balanced pair adopt did not author
was the missing fourth, and the only destructive one.

The fix is authorship, not integrity: the begin marker adopt writes carries
`sha256=<16 hex of the body>`, and **only a signed pair is adopt's**. Anything
else is inert prose that is never searched, matched or touched.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from aef.cli.adopt import (
    MD_MARKERS,
    apply_block,
    carries_adopt_block,
    resolve_block_span,
    run_adopt,
    signed_begin,
)

RULE = "RULE 7: never deploy on a Friday, and never without the migration dry run."
QUOTED_PAIR = f"""# House rules

Our `aef adopt` block is delimited like this:

<!-- aef:begin -->
{RULE}
<!-- aef:end -->

Everything above is ours.
"""


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a16_a_quoted_marker_pair_survives_adopt(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    """The whole file, through the real `run_adopt`."""
    root = tmp_path / "repo"
    new_repo(root)
    (root / "CLAUDE.md").write_text(QUOTED_PAIR, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "the adopter's own rules")

    run_adopt(root)

    after = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert RULE in after, "adopt deleted the text between the adopter's own quoted markers"
    assert after.startswith(QUOTED_PAIR), (
        "the adopter's bytes are no longer a verbatim prefix of the result"
    )


def test_a16_the_bare_pair_is_not_recognised_as_adopts(attack_log: list[str]) -> None:
    """The predicate underneath, on its own. `carries_adopt_block` returning
    True here is what made the destruction happen."""
    assert not carries_adopt_block(QUOTED_PAIR, MD_MARKERS)

    action, start, stop = resolve_block_span(QUOTED_PAIR, MD_MARKERS)  # type: ignore[misc]
    attack_log.append(f"{action} [{start}:{stop}] of {len(QUOTED_PAIR)}")
    assert action == "append", attack_log
    assert start == stop == len(QUOTED_PAIR), attack_log


def test_a16_adopts_own_signed_block_IS_recognised_and_replaced() -> None:
    """The control for the control. If nothing were ever recognised, the test
    above would pass on a tool that had stopped maintaining its own block, and
    a second `aef adopt` would append a second copy."""
    body = "## AEF scaffold (generated)\n\nfirst version"
    begin, end = MD_MARKERS
    text = f"before\n\n{signed_begin(begin, body)}\n{body}\n{end}\n\nafter\n"

    assert carries_adopt_block(text, MD_MARKERS)
    replacement_body = "## AEF scaffold (generated)\n\nsecond version"
    replacement = f"{signed_begin(begin, replacement_body)}\n{replacement_body}\n{end}"
    out = apply_block(text, replacement, MD_MARKERS)

    assert out is not None
    assert "second version" in out
    assert "first version" not in out
    assert out.startswith("before\n\n") and out.endswith("\n\nafter\n")


def test_a16_two_signed_begins_are_refused_rather_than_guessed_at() -> None:
    """The remaining ambiguity is refused, not resolved. Guessing where
    someone else's block ends is how a never-overwrite tool overwrites."""
    begin, end = MD_MARKERS
    body = "## AEF scaffold (generated)\n\nx"
    twice = (
        f"{signed_begin(begin, body)}\n{body}\n{end}\n{signed_begin(begin, body)}\n{body}\n{end}"
    )
    assert resolve_block_span(twice, MD_MARKERS) is None
    assert apply_block(twice, "irrelevant", MD_MARKERS) is None


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a16_the_control_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, attack_log: list[str]
) -> None:
    """Make the begin-marker pattern match a BARE pair — the pre-ADR-0172
    behaviour, one regex — and the adopter's house rules are deleted.

    Nothing else changes: the same `apply_block`, the same never-overwrite
    intent, the same reported outcome. The discriminator between "adopt's
    block" and "the adopter's prose" was the whole defence.
    """
    import re

    import aef.cli.adopt as adopt

    monkeypatch.setattr(adopt, "_signed_begin_re", lambda begin: re.compile(re.escape(begin)))

    replacement = "<!-- aef:begin sha256=0000000000000000 -->\nGENERATED\n<!-- aef:end -->"
    out = adopt.apply_block(QUOTED_PAIR, replacement, MD_MARKERS)
    attack_log.append(repr(out))

    assert out is not None, attack_log
    assert RULE not in out, (
        "the adopter's rule survived even with the signature check removed, so the signature "
        f"is not what saved it and the attack above proves less: {attack_log}"
    )
    assert "Everything above is ours." in out, (
        "the mutation destroyed more than the reproduced defect did; the fixture no longer "
        "matches ADR 0172's case"
    )
