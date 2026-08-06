"""`aef migrate` — the mechanical half of what `adopt` only documents.

The two tests that matter are `test_the_outermost_wrapper_is_chosen` and
`test_dot_directories_are_not_scanned`: both are regressions for defects the
first version had against a real repo, not hypotheticals.
"""

from __future__ import annotations

from pathlib import Path

from aef.cli.migrate import render, run_migrate, scan


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_a_function_wrapping_a_vendor_call_is_found(tmp_path: Path) -> None:
    _write(
        tmp_path, "svc.py", "import anthropic\n\ndef ask(p):\n    return anthropic.Anthropic()\n"
    )
    result = scan(tmp_path)
    assert [(s.module, s.function) for s in result.sites] == [("svc", "ask")]
    assert "anthropic.Anthropic" in result.sites[0].evidence


def test_the_outermost_wrapper_is_chosen_not_the_raw_sdk_call(tmp_path: Path) -> None:
    """The defect the first version shipped, reproduced against a real repo.

    It wrapped `_call_api` — the private function constructing the client —
    while the repo's actual seam was the public function above it carrying the
    retries, budgets and backend order. Wrapping the inner one bypasses all of
    them, which the module docstring explicitly says not to do.
    """
    _write(
        tmp_path,
        "client.py",
        "import anthropic\n\n"
        "def _call_api(p):\n    return anthropic.Anthropic()\n\n"
        "def call_with_backend(p):\n    return _call_api(p)\n\n"
        "def call(p):\n    return call_with_backend(p)\n",
    )
    result = scan(tmp_path)
    chosen = [s.function for s in result.sites]
    assert chosen == ["call"], f"expected the outermost wrapper, got {chosen}"
    assert "_call_api" not in chosen
    assert "transitively" in result.sites[0].evidence


def test_dot_directories_are_not_scanned(tmp_path: Path) -> None:
    """Also a real-repo regression: two of the first run's four 'call sites'
    were duplicate copies inside `.codex/worktrees/`."""
    body = "import anthropic\n\ndef ask(p):\n    return anthropic.Anthropic()\n"
    _write(tmp_path, "svc.py", body)
    _write(tmp_path, ".codex/worktrees/copy/svc.py", body)
    _write(tmp_path, ".venv/lib/vendored.py", body)
    result = scan(tmp_path)
    assert [s.module for s in result.sites] == ["svc"]


def test_async_is_skipped_with_its_reason(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "import anthropic\n\nasync def ask(p):\n    return anthropic.Anthropic()\n",
    )
    result = scan(tmp_path)
    assert not result.sites
    assert len(result.skipped) == 1
    assert "async" in result.skipped[0].reason


def test_methods_are_skipped_with_their_reason(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "m.py",
        "import anthropic\n\nclass Gate:\n"
        "    def ask(self, p):\n        return anthropic.Anthropic()\n",
    )
    result = scan(tmp_path)
    assert not result.sites
    assert "method" in result.skipped[0].reason


def test_generators_are_skipped_with_their_reason(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "g.py",
        "import anthropic\n\ndef stream(p):\n    yield anthropic.Anthropic()\n",
    )
    result = scan(tmp_path)
    assert not result.sites
    assert "generator" in result.skipped[0].reason


def test_a_repo_with_no_vendor_call_yields_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "plain.py", "def add(a, b):\n    return a + b\n")
    result = scan(tmp_path)
    assert not result.sites and not result.skipped


def test_generated_module_is_valid_python_and_imports_the_real_function(tmp_path: Path) -> None:
    import ast as _ast

    _write(
        tmp_path, "svc.py", "import anthropic\n\ndef ask(p):\n    return anthropic.Anthropic()\n"
    )
    result = scan(tmp_path)
    source = render(result, "demo")
    _ast.parse(source)  # raises if the template emits invalid Python
    assert "from svc import ask" in source
    assert "ask(state.objective)" in source


def test_an_empty_result_refuses_to_emit_a_graph(tmp_path: Path) -> None:
    """A build_graph() returning an empty graph would look like a migration
    that succeeded and does nothing. It raises instead."""
    import ast as _ast

    source = render(scan(tmp_path), "demo")
    _ast.parse(source)
    assert "raise NotImplementedError" in source


def test_run_migrate_never_overwrites_without_force(tmp_path: Path) -> None:
    _write(
        tmp_path, "svc.py", "import anthropic\n\ndef ask(p):\n    return anthropic.Anthropic()\n"
    )
    first = run_migrate(tmp_path)
    assert first.written is not None
    (tmp_path / "aef_migrated.py").write_text("# hand-edited\n", encoding="utf-8")

    second = run_migrate(tmp_path)
    assert second.written is None, "must not overwrite an edited generated file"
    assert (tmp_path / "aef_migrated.py").read_text() == "# hand-edited\n"

    third = run_migrate(tmp_path, force=True)
    assert third.written is not None
    assert "# hand-edited" not in (tmp_path / "aef_migrated.py").read_text()


def test_report_names_what_was_skipped(tmp_path: Path) -> None:
    """A tool that emits nodes for some call sites and stays silent about the
    rest is how a repo gets believed migrated when it is not."""
    _write(
        tmp_path,
        "mix.py",
        "import anthropic\n\n"
        "def ok(p):\n    return anthropic.Anthropic()\n\n"
        "async def nope(p):\n    return anthropic.Anthropic()\n",
    )
    from aef.cli.migrate import report

    text = report(run_migrate(tmp_path, write=False))
    assert "WRAPPED" in text and "SKIPPED" in text
    assert "1 wrapped, 1 skipped" in text
    assert "not the semantics" in text
