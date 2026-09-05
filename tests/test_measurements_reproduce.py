"""The published measurement tables re-derive from committed data (ADR 0196).

ADR 0188 gave dimension 5 nine of ten and named the missing point: headline
numbers reaching a reader as prose, the data one directory away, and no
re-runner regenerating the tables in CI. ADR 0191 then withdrew S1c's `+2`
*because its seed no longer reproduced* — noticed a night later, during a
hunt, rather than by anything that runs.

This is the CI half of `make measure`. It runs the fast subset — every runner
that reads committed JSON/JSONL, which excludes the two that replay a corpus
through a cassette — and asserts that the set of rows which drift is EXACTLY
the set `measure.py` records with a reason. That is a two-sided assertion:

* a new drift fails, which is the regression this exists to catch;
* a known drift that starts reproducing again ALSO fails, so a note whose
  explanation has gone stale cannot outlive the drift it explains.

Zero live model calls, here and in `measure.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MEASURE = REPO_ROOT / "docs" / "research" / "measure.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("aef_measure", MEASURE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["aef_measure"] = module
    spec.loader.exec_module(module)
    return module


measure = _load()

FAST = [m for m in measure.MEASUREMENTS if m.speed == "fast"]


def test_the_registry_is_not_empty_and_every_runner_exists() -> None:
    assert FAST, "the fast subset is empty — CI would assert nothing"
    for m in measure.MEASUREMENTS:
        assert (REPO_ROOT / m.argv[0]).exists(), m.argv[0]
        assert (REPO_ROOT / m.adr).exists(), m.adr
        assert m.rows, f"{m.id} pins no rows"


def test_every_known_drift_note_names_an_adr() -> None:
    """A note that explains nothing is a silencer. Each must cite an ADR."""
    for m in measure.MEASUREMENTS:
        if m.known_failure:
            assert "ADR" in m.known_failure, m.id
        for row in m.rows:
            if row.known_drift:
                assert "ADR" in row.known_drift, f"{m.id}/{row.name}"


@pytest.mark.parametrize("m", FAST, ids=[m.id for m in FAST])
def test_the_published_table_re_derives(m) -> None:  # type: ignore[no-untyped-def]
    """Every pinned row either reproduces or is a recorded, explained drift."""
    results = measure.check(m, REPO_ROOT)
    unexplained = [r for r in results if r.status in measure.BAD]
    assert not unexplained, "\n".join(
        f"{r.key}: ADR says {r.published!r}, re-derived {r.derived!r} {r.detail}"
        for r in unexplained
    )
    observed = {r.key for r in results if r.status == "xfail"}
    expected = {f"{m.id}/{row.name}" for row in m.rows if row.known_drift}
    if m.known_failure:
        expected.add(f"{m.id}/<runner>")
    assert observed == expected, (
        f"the drift set for {m.id} changed: new {sorted(observed - expected)}, "
        f"healed {sorted(expected - observed)}"
    )


def test_a_perturbed_published_number_is_caught(tmp_path: Path) -> None:
    """The mutation this file exists to survive: change a number in an ADR and
    `measure.py` must name it. Run against a COPY of the repo tree so nothing
    committed is touched."""
    target = next(m for m in FAST if m.id == "i12b-arms")
    adr = REPO_ROOT / target.adr
    original = adr.read_text()
    assert "| (b) raw records | **0.9176** |" in original, "anchor moved"

    # A shadow root: symlink everything, then override the one ADR.
    shadow = tmp_path / "root"
    shadow.mkdir()
    for child in REPO_ROOT.iterdir():
        if child.name != "docs":
            (shadow / child.name).symlink_to(child)
    (shadow / "docs").mkdir()
    for child in (REPO_ROOT / "docs").iterdir():
        if child.name != "adr":
            (shadow / "docs" / child.name).symlink_to(child)
    (shadow / "docs" / "adr").mkdir()
    for child in (REPO_ROOT / "docs" / "adr").iterdir():
        if child.name != adr.name:
            (shadow / "docs" / "adr" / child.name).symlink_to(child)
    (shadow / "docs" / "adr" / adr.name).write_text(
        original.replace("| (b) raw records | **0.9176** |", "| (b) raw records | **0.9999** |")
    )

    results = measure.check(target, shadow)
    drifted = [r for r in results if r.status == "drift"]
    assert [r.row for r in drifted] == ["(b) raw records, mean"], [
        (r.row, r.status) for r in results
    ]
    assert drifted[0].published == "0.9999" and drifted[0].derived == "0.9176"
    # And the control: the unperturbed rows still reproduce.
    assert sum(1 for r in results if r.status == "ok") == len(target.rows) - 1
    assert adr.read_text() == original, "the real ADR was written to"
