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


# --------------------------------------------------------------------------
# ADR 0137 — routed vs unrouted, and how migrate decides
#
# The rule, in one sentence: route only a function that is nothing but the
# call. Everything else keeps its own body and is told, in its own docstring,
# that its model call is invisible to the harness. Each test below names one
# specific thing routing would otherwise have dropped silently.
# --------------------------------------------------------------------------

THIN = (
    "import anthropic\n\n"
    "def ask(p):\n"
    "    client = anthropic.Anthropic()\n"
    "    r = client.messages.create(model='claude-sonnet-4-6', max_tokens=100,\n"
    "                               messages=[{'role': 'user', 'content': p}])\n"
    "    return r.content[0].text\n"
)

UNROUTABLE = "import anthropic\n\ndef ask(p):\n    return anthropic.Anthropic()\n"


def _only_site(root: Path):
    result = scan(root)
    assert len(result.sites) == 1, [s.function for s in result.sites]
    return result.sites[0]


def test_a_thin_direct_wrapper_gets_the_routed_form(tmp_path: Path) -> None:
    """The shape the ready loop measured: eight lines, builds its own client,
    makes one call. Nothing here for routing to lose, so route it."""
    _write(tmp_path, "svc.py", THIN)
    site = _only_site(tmp_path)
    assert site.routed
    assert site.model == "claude-sonnet-4-6"
    assert site.max_tokens == 100

    source = render(scan(tmp_path), "demo")
    assert "services.require_model_provider().complete(" in source
    assert 'model="claude-sonnet-4-6"' in source
    assert "from svc import ask" not in source, "a routed node must not call the function"
    assert "IS NOT CALLED by this node" in source


def test_a_retry_loop_is_not_routed(tmp_path: Path) -> None:
    """The falsification clause. A `for` around the call is a retry or backoff
    policy and `complete()` is one shot, so routing would drop it silently."""
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    for _ in range(3):\n"
        "        return client.messages.create(model='m', messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "loops" in site.form_reason


def test_a_try_except_is_not_routed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    try:\n"
        "        return client.messages.create(model='m', messages=[])\n"
        "    except Exception:\n"
        "        return None\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "catches exceptions" in site.form_reason


def test_a_streaming_call_is_not_routed(tmp_path: Path) -> None:
    """`ModelProvider.complete()` returns once. Routing a stream changes the
    shape of the answer the caller reads — a rewrite, not plumbing."""
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='m', messages=[], stream=True)\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "stream" in site.form_reason


def test_an_injected_client_is_not_routed(tmp_path: Path) -> None:
    """Nothing here says which vendor or which model. migrate will not guess."""
    _write(
        tmp_path,
        "svc.py",
        "def ask(client, p):\n    return client.messages.create(model='m', messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "injected or global" in site.form_reason


def test_an_outer_backend_wrapper_is_not_routed(tmp_path: Path) -> None:
    """The exact shape `outermost` exists for: the public function carries the
    retries and backend order, the private one holds the SDK call. It is still
    the right node to WRAP and it is the wrong one to ROUTE — its whole value
    is the machinery routing would bypass."""
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def _call(p):\n"
        "    c = anthropic.Anthropic()\n"
        "    return c.messages.create(model='m', messages=[])\n\n"
        "def call_with_backend(p):\n"
        "    return _call(p)\n",
    )
    site = _only_site(tmp_path)
    assert site.function == "call_with_backend"
    assert not site.routed
    assert "wraps another function" in site.form_reason


def test_a_non_literal_model_is_not_routed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "MODEL = 'm'\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model=MODEL, messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "not a literal" in site.form_reason


def test_a_function_that_does_more_than_call_is_not_routed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    log_it(p)\n"
        "    return client.messages.create(model='m', messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "log_it()" in site.form_reason


def test_the_routed_node_imports_no_vendor_sdk(tmp_path: Path) -> None:
    """The point of the increment, asserted with the same scanner the preflight
    obligation uses rather than with a substring search."""
    from aef.harness.vendor_scan import scan_source

    _write(tmp_path, "svc.py", THIN)
    source = render(scan(tmp_path), "demo")
    assert scan_source(source, path=Path("<generated>")) == []


def test_the_unrouted_node_warns_that_its_call_is_invisible(tmp_path: Path) -> None:
    """Before ADR 0137 the generated wrapper said nothing at all, and the
    adopter found out at gate time when the cassette had nothing to replay."""
    _write(tmp_path, "svc.py", UNROUTABLE)
    source = render(scan(tmp_path), "demo")
    assert "UNROUTED" in source
    assert "does NOT pass through" in source
    assert 'on_miss="fail"' in source
    assert "score the scenario 0" in source


def test_the_report_says_which_form_it_chose_and_why(tmp_path: Path) -> None:
    from aef.cli.migrate import report

    _write(tmp_path, "thin.py", THIN)
    _write(
        tmp_path,
        "fat.py",
        "import anthropic\n\n"
        "def ask2(p):\n"
        "    c = anthropic.Anthropic()\n"
        "    try:\n"
        "        return c.messages.create(model='m', messages=[])\n"
        "    except Exception:\n"
        "        return None\n",
    )
    text = report(run_migrate(tmp_path, write=False))
    assert "ROUTED" in text and "WRAPPED" in text
    assert "1 routed through Services.model_provider, 1 still calling your function" in text
    assert "routed because" in text
    assert "NOT routed because" in text
    assert "is now BYPASSED" in text
    assert "INVISIBLE to the harness" in text


def _ruff_the_generated_module(root: Path, name: str, body: str) -> str:
    """Render a module from a one-file repo and run the repo's OWN ruff on it."""
    import subprocess

    _write(root, name, body)
    source = render(scan(root), "demo")
    out = root / "generated" / "aef_migrated.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            "ruff",
            "check",
            "--isolated",
            "--line-length",
            "100",
            "--target-version",
            "py311",
            "--select",
            "E,F,I,UP,B,TID",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return source


def test_every_generated_form_passes_the_repos_own_ruff(tmp_path: Path) -> None:
    """A generated file that fails the lint of the repo it lands in is a chore
    handed over, not work done — and all three forms failed it before ADR 0137:
    two `E501`s from an unwrapped `def` line and an unwrapped `Node(...)`, and
    an `F401` in the empty form, which imported `Any` and never used it. Nobody
    had run ruff on the output.
    """
    _ruff_the_generated_module(tmp_path / "routed", "svc.py", THIN)
    _ruff_the_generated_module(tmp_path / "unrouted", "svc.py", UNROUTABLE)
    _ruff_the_generated_module(tmp_path / "empty", "plain.py", "def add(a, b):\n    return a + b\n")


def test_both_generated_forms_are_importable(tmp_path: Path) -> None:
    """`ast.parse` says it is syntactically Python. Executing it says the
    imports resolve and `build_graph()` builds a Graph the kernel accepts."""
    import importlib.util

    for name, body in (("routed", THIN), ("unrouted", UNROUTABLE)):
        root = tmp_path / name
        _write(root, "svc.py", body)
        out = root / "aef_migrated.py"
        out.write_text(render(scan(root), name), encoding="utf-8")

        spec = importlib.util.spec_from_file_location(f"gen_{name}", out)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        graph = module.build_graph()
        assert graph.id == name
        assert graph.entry_node in graph.nodes


def test_a_repo_under_a_dot_directory_is_still_scanned(tmp_path: Path) -> None:
    """NEW DEFECT, found while reproducing K1. `_skip` tested the ABSOLUTE
    path, so a repo living anywhere under a dot-directory — `~/.local/src/app`,
    a git worktree under `.claude/`, a checkout in `.build/` — had every one of
    its files skipped and was reported as `scanned 0 Python file(s) ... 0 call
    site(s)`, exit 0. The tool said the repo had no model calls because it had
    refused to look at the repo.

    The dot-directory rule still applies WITHIN the repo, which is what it was
    written for (`.codex/worktrees/` duplicates); that half is asserted too.
    """
    root = tmp_path / ".hidden" / "worktrees" / "repo"
    _write(root, "svc.py", UNROUTABLE)
    _write(root, ".codex/copy/svc.py", UNROUTABLE)
    result = scan(root)
    assert result.scanned_files == 1, "the repo's own file must be scanned"
    assert [s.module for s in result.sites] == ["svc"], "the in-repo dot-dir must still be skipped"
