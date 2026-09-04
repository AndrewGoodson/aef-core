"""Constraint #3: vendor SDK imports appear ONLY inside `aef/providers/`
and `aef/services/*/adapters/`. This AST-scans `aef/kernel/`,
`aef/reasoning/`, and `aef/agents/` and fails if any of them import a
vendor SDK directly. CI runs this as its own step so the isolation can't
regress silently.

**The scanner itself now lives in `aef/harness/vendor_scan.py`.** It was
defined here for five phases, which meant the one detector that knows what a
vendor SDK import looks like could only ever be pointed at this repo — an
adopted repo's node constructing its own `anthropic.Anthropic()` bypasses the
policy engine and the fallback chain identically, and nothing looked (ADR
0137). This file keeps the constraint and the scanner's own regression tests;
`aef/harness/preflight.py` and `aef/cli/migrate.py` share the same code and
the same list.
"""

from __future__ import annotations

from pathlib import Path

from aef.harness.vendor_scan import (
    MODEL_SDK_ROOTS,
    VENDOR_TOP_LEVEL_MODULES,
    scan_file,
    scan_source,
)

REPO_ROOT = Path(__file__).parent.parent
BANNED_ZONES = ["aef/kernel", "aef/reasoning", "aef/agents"]


def _iter_python_files(zone: Path) -> list[Path]:
    return sorted(zone.rglob("*.py"))


def _find_violations(path: Path) -> list[str]:
    return [str(v) for v in scan_file(path)]


def test_no_vendor_imports_in_banned_zones() -> None:
    all_violations: list[str] = []
    for zone_name in BANNED_ZONES:
        zone_path = REPO_ROOT / zone_name
        assert zone_path.is_dir(), f"expected banned zone {zone_path} to exist"
        for py_file in _iter_python_files(zone_path):
            all_violations.extend(_find_violations(py_file))

    assert not all_violations, (
        "vendor SDK imports found outside providers/services/*/adapters:\n"
        + "\n".join(all_violations)
    )


def test_scanner_actually_detects_a_violation(tmp_path: Path) -> None:
    """Meta-test: prove the AST scanner isn't a no-op that would pass on
    anything. A real violation must be caught."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("import anthropic\nfrom openai import OpenAI\n")
    violations = _find_violations(bad_file)
    assert len(violations) == 2


def test_scanner_ignores_relative_imports(tmp_path: Path) -> None:
    ok_file = tmp_path / "ok.py"
    ok_file.write_text("from . import sibling\nfrom .base import Thing\n")
    assert _find_violations(ok_file) == []


def test_scanner_catches_aliased_import(tmp_path: Path) -> None:
    bad_file = tmp_path / "aliased.py"
    bad_file.write_text("import anthropic as anthro\n")
    assert len(_find_violations(bad_file)) == 1


def test_scanner_catches_import_nested_inside_a_function(tmp_path: Path) -> None:
    """`ast.walk` traverses the whole tree, not just module-level
    statements — a lazy/deferred import hidden inside a function body must
    be caught too, not just an obvious top-of-file import."""
    bad_file = tmp_path / "nested.py"
    bad_file.write_text("def build():\n    import anthropic\n    return anthropic\n")
    assert len(_find_violations(bad_file)) == 1


def test_scanner_catches_import_inside_try_except(tmp_path: Path) -> None:
    bad_file = tmp_path / "lazy.py"
    bad_file.write_text(
        "def build():\n    try:\n        import openai\n    except ImportError:\n        "
        "openai = None\n    return openai\n"
    )
    assert len(_find_violations(bad_file)) == 1


def test_scanner_catches_import_inside_type_checking_block(tmp_path: Path) -> None:
    """Deliberately stricter than the constraint needs to be: a
    TYPE_CHECKING-only vendor import has no runtime cost, but nothing in
    this repo currently needs one (confirmed: no banned zone uses
    TYPE_CHECKING today), and banning it too keeps the rule simple — a
    type hint needing a vendor type should reference it through
    aef/providers/'s own types, not the vendor SDK directly."""
    bad_file = tmp_path / "typecheck.py"
    bad_file.write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import anthropic\n"
    )
    assert len(_find_violations(bad_file)) == 1


# --------------------------------------------------------------------------
# The lift itself (ADR 0137)
# --------------------------------------------------------------------------


def test_the_scanner_reports_which_vendor_and_where(tmp_path: Path) -> None:
    """The preflight obligation names the module and the vendor in its
    message, so the scanner must carry both rather than a formatted string."""
    bad_file = tmp_path / "svc.py"
    bad_file.write_text("import os\nimport anthropic\n")
    (found,) = scan_file(bad_file)
    assert found.module == "anthropic"
    assert found.lineno == 2
    assert found.statement == "import anthropic"


def test_model_sdk_roots_are_a_subset_of_the_vendor_list() -> None:
    """One list, not two. `migrate` asks a narrower question than constraint
    #3 does — `opentelemetry` is a vendor SDK and is not a model call — but a
    root it treats as a model SDK that the isolation list does not know about
    would be exactly the drift ADR 0091 names."""
    assert MODEL_SDK_ROOTS <= VENDOR_TOP_LEVEL_MODULES, sorted(
        MODEL_SDK_ROOTS - VENDOR_TOP_LEVEL_MODULES
    )


def test_an_unparseable_file_is_not_reported_as_a_vendor_import(tmp_path: Path) -> None:
    """A syntax error is a file the scanner cannot speak about. Reporting it
    as a violation would put a false claim in the adopter's message."""
    bad_file = tmp_path / "broken.py"
    bad_file.write_text("def f(:\n")
    assert scan_file(bad_file) == []


def test_scan_source_takes_text_so_generated_code_can_be_checked() -> None:
    """`aef migrate` renders a module before writing it; the tests that assert
    the generated node does not import a vendor SDK scan the text, not a
    file."""
    assert scan_source("import anthropic\n", path=Path("<generated>")) != []
    assert scan_source("from aef.kernel import END\n", path=Path("<generated>")) == []
