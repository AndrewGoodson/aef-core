"""ADR 0110's structural claim, enforced rather than asserted in prose.

The knowledge layer does not unblock evolution. `aef/evolution/` stays
hard-disabled under constraint #7, and the three findings that make
`docs/trust/promotion-trust-case.md` recommend against auto-merge are untouched
by a consolidation layer.

A prose claim in an ADR is a convention. This is the same AST-scan technique
`tests/test_vendor_isolation.py` uses for constraint #3, applied in both
directions — because the coupling could arrive from either side, and a scan
that only looks one way would pass while the property was already broken.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent
KNOWLEDGE = "aef.services.knowledge"
EVOLUTION = "aef.evolution"


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    """Every absolute module name imported by `path`, with its line number.

    `ast.walk` rather than a scan of module-level statements, for the reason
    the vendor scanner does it: a deferred import inside a function body is
    still an import, and is exactly where someone would put one to avoid a
    circular-import complaint.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level > 0:
                continue  # relative import — cannot cross packages
            found.append((node.lineno, node.module))
    return found


def _violations(zone: Path, forbidden_prefix: str) -> list[str]:
    out: list[str] = []
    for py_file in sorted(zone.rglob("*.py")):
        for lineno, module in _imported_modules(py_file):
            if module == forbidden_prefix or module.startswith(forbidden_prefix + "."):
                out.append(f"{py_file}:{lineno}: imports {module}")
    return out


def test_knowledge_does_not_import_evolution() -> None:
    zone = REPO_ROOT / "aef" / "services" / "knowledge"
    assert zone.is_dir(), f"expected {zone} to exist"
    violations = _violations(zone, EVOLUTION)
    assert not violations, (
        "the knowledge layer imports the evolution engine, which ADR 0110 forbids "
        "structurally — consolidation does not feed automated promotion:\n" + "\n".join(violations)
    )


def test_evolution_does_not_import_knowledge() -> None:
    zone = REPO_ROOT / "aef" / "evolution"
    assert zone.is_dir(), f"expected {zone} to exist"
    violations = _violations(zone, KNOWLEDGE)
    assert not violations, (
        "the evolution engine imports the knowledge layer. Consolidated knowledge is "
        "not evidence for promotion: the trust case's three findings are about live "
        "traffic, real tenants, and shadow containment, none of which a wiki moves:\n"
        + "\n".join(violations)
    )


def test_scanner_detects_a_planted_cross_import(tmp_path: Path) -> None:
    """Meta-test. A scanner that cannot detect is not a scanner — one audit
    script in this program returned a false negative on the very claim it was
    checking."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from aef.evolution.engine import EvolutionConfig\nimport aef.evolution\n",
    )
    assert len(_violations(tmp_path, EVOLUTION)) == 2


def test_scanner_detects_a_deferred_cross_import(tmp_path: Path) -> None:
    """The realistic shape: an import moved inside a function to dodge a
    circular-import error, which also dodges a module-level-only scan."""
    bad = tmp_path / "deferred.py"
    bad.write_text("def promote():\n    from aef.evolution import engine\n    return engine\n")
    assert len(_violations(tmp_path, EVOLUTION)) == 1


def test_scanner_does_not_flag_a_similarly_named_module(tmp_path: Path) -> None:
    """Prefix matching must respect module boundaries: `aef.evolutionary` is
    not `aef.evolution`, and a scanner that conflates them would fail a
    correct file."""
    ok = tmp_path / "ok.py"
    ok.write_text("import aef.evolutionary_notes\nfrom aef.services.memory import base\n")
    assert _violations(tmp_path, EVOLUTION) == []
