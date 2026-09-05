"""The red team, as code.

`docs/trust/promotion-trust-case.md` §2 reports an adversarial round: seven
attacks, three outcomes, two of which broke the system. Until this directory
existed that record was **prose plus a grep** — `tests/harness/test_trust_case.py`
asserted the document still said "BROKE IT" twice, and a comment in it mapped
each attack to the test that happened to exercise the same control. An
independent reviewer read that mapping and scored it exactly as it deserved:

    "adversarial rounds exist as a document I was not allowed to read, not as
     an executable red-team suite"                          (ADR 0188, dim 4)

A document is not a control. Every module here does three things, in order:

1. **Builds the hostile input** — the candidate, the tag, the config, the
   diff, the manifest — rather than describing it.
2. **Runs it through the real control**, imported from `aef/`, and asserts
   the refusal. Not a stub of the control, and never a re-implementation.
3. **Mutates the control away and asserts the attack then LANDS.** This is
   what separates a red team from a green bar: a test that passes because
   the exploit was never viable is indistinguishable, from the outside, from
   a test that passes because the defence worked. The mutation is in-process
   (`monkeypatch`), so it is re-runnable in CI and cannot leave the tree
   edited.

Run it: `pytest -m adversarial` (or `tests/adversarial/redteam.sh`).

**What this suite is not.** It is still written by the party that wrote the
defences, which is the limitation §3 of the trust case prices in and which no
amount of automation removes. What it removes is the *staleness*: an attack
whose defence is deleted now fails a test instead of leaving a paragraph.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test under this directory is `adversarial`, without each module
    remembering to say so — a marker applied by hand is a marker one new file
    forgets, and `pytest -m adversarial` would then quietly run less than the
    suite claims."""
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.adversarial)


@pytest.fixture
def git() -> Callable[..., None]:
    def run(root: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    return run


@pytest.fixture
def new_repo(git: Callable[..., None]) -> Callable[[Path], None]:
    """An initialised repo with an identity, so commits do not depend on the
    machine's git config."""

    def init(root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "redteam@example.com")
        git(root, "config", "user.name", "red team")

    return init


@pytest.fixture
def attack_log() -> Iterator[list[str]]:
    """Somewhere for a module to record what it actually observed, printed on
    failure. An attack test that fails with a bare `assert` teaches nothing
    about which half broke."""
    lines: list[str] = []
    yield lines
