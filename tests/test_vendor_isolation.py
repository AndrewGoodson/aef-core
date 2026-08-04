"""Constraint #3: vendor SDK imports appear ONLY inside `aef/providers/`
and `aef/services/*/adapters/`. This AST-scans `aef/kernel/`,
`aef/reasoning/`, and `aef/agents/` and fails if any of them import a
vendor SDK directly. CI runs this as its own step so the isolation can't
regress silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BANNED_ZONES = ["aef/kernel", "aef/reasoning", "aef/agents"]

# Every vendor/product SDK named or implied by the research report and
# blueprint as a pluggable backend. Not exhaustive by construction — extend
# this set whenever a new adapter is added under providers/ or
# services/*/adapters/.
BANNED_TOP_LEVEL_MODULES = frozenset(
    {
        "anthropic",
        "openai",
        "mem0",
        "mem0ai",
        "neo4j",
        "falkordb",
        "memgraph",
        "temporalio",
        "psycopg",
        "psycopg2",
        "opentelemetry",
        "dspy",
        "gepa",
        "llmlingua",
        "ragas",
        "deepeval",
        "langfuse",
        "google",
    }
)


def _iter_python_files(zone: Path) -> list[Path]:
    return sorted(zone.rglob("*.py"))


def _top_level_module(name: str) -> str:
    return name.split(".", 1)[0]


def _find_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = _top_level_module(alias.name)
                if mod in BANNED_TOP_LEVEL_MODULES:
                    violations.append(f"{path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level > 0:
                continue  # relative import, e.g. "from . import x" — always in-package
            mod = _top_level_module(node.module)
            if mod in BANNED_TOP_LEVEL_MODULES:
                violations.append(f"{path}:{node.lineno}: from {node.module} import ...")
    return violations


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
