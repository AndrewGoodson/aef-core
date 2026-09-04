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


# --------------------------------------------------------------------------
# ADR 0140 — what the routable predicate refuses now, and why
#
# ADR 0137's falsification clause enumerated retries, streams and backends —
# control flow — and never asked whether the REQUEST survives translation into
# `CompletionRequest`. Four shapes were routed that dropped something real.
# Each test below is one of them, reproduced before it was fixed.
# --------------------------------------------------------------------------


def test_a_system_prompt_is_not_routed_because_there_is_nowhere_to_put_it(tmp_path: Path) -> None:
    """REPRODUCED: a claims adjuster whose `system=` said "NEVER approve a
    payout above $5,000" was routed, and the generated node carried only
    messages/model/max_tokens. `CompletionRequest` has no `system` field, so
    "yours to re-express" named a place that does not exist — while the
    generated docstring said "there is nothing here for routing to lose".
    """
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    r = client.messages.create(\n"
        "        model='claude-sonnet-4-6', max_tokens=8192,\n"
        "        system='You are a claims adjuster. NEVER approve above $5,000.',\n"
        "        tools=[{'name': 'lookup_policy'}],\n"
        "        stop_sequences=['</done>'],\n"
        "        messages=[{'role': 'user', 'content': p}],\n"
        "    )\n"
        "    return r.content[0].text\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "system=" in site.form_reason
    assert "tools=" in site.form_reason and "stop_sequences=" in site.form_reason
    assert "no system field" in site.form_reason
    assert "semantic decision" in site.form_reason

    source = render(scan(tmp_path), "demo")
    assert "UNROUTED wrapper" in source, "must not route away a system prompt"
    assert "from svc import ask" in source, "the adopter's function keeps its own request"
    assert "CompletionRequest(" not in source
    assert "NEVER approve" not in source


def test_a_keyword_the_request_type_cannot_express_is_not_routed(tmp_path: Path) -> None:
    """Without `system=`, the refusal still names the exact keywords."""
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='m', max_tokens=10, messages=[],\n"
        "                                  tool_choice={'type': 'any'})\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "tool_choice=" in site.form_reason


def test_the_routable_keywords_are_read_off_the_request_type(tmp_path: Path) -> None:
    """The anti-drift assertion (ADR 0091's rule, applied to this predicate).

    A second hardcoded list here is how the defect happened: the predicate
    judged control flow and had no idea what `CompletionRequest` holds. Adding
    a field to the request type must widen this set on the same commit.
    """
    from dataclasses import fields as _fields

    from aef.cli.migrate import _CARRIED_FIELDS, _REQUEST_FIELDS
    from aef.providers.base import CompletionRequest

    declared = {f.name for f in _fields(CompletionRequest)}
    assert _REQUEST_FIELDS == frozenset(declared) | {"messages"}
    assert set(_CARRIED_FIELDS) == declared - {"messages"}
    assert "system" not in _REQUEST_FIELDS, "the whole point: the request type has no system field"


def test_a_carried_keyword_is_reproduced_verbatim_in_the_routed_node(tmp_path: Path) -> None:
    """Expressible keywords are carried, not silently defaulted."""
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='claude-sonnet-4-6', max_tokens=77,\n"
        "                                  temperature=0.0, messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert site.routed
    assert site.request_args == (
        ("model", '"claude-sonnet-4-6"'),
        ("max_tokens", "77"),
        ("temperature", "0.0"),
    )
    source = render(scan(tmp_path), "demo")
    assert "temperature=0.0," in source, "a carried keyword must reach the generated request"


def test_a_non_literal_expressible_keyword_is_not_routed(tmp_path: Path) -> None:
    """`max_tokens=MAX` used to route as no max_tokens at all, so
    `CompletionRequest`'s default (16000) silently replaced the adopter's cap.
    """
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "MAX = 256\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='m', max_tokens=MAX, messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "max_tokens=" in site.form_reason and "not a literal" in site.form_reason


def test_a_bare_decorator_is_not_routed(tmp_path: Path) -> None:
    """REPRODUCED: `@retry` bare is an `ast.Name`, not an `ast.Call`, so it
    left no `Call` node for the "body also calls retry()" rule to trip over.
    The called form `@retry(...)` was caught only by that accident. Retries
    were dropped for the bare form, silently.
    """
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n"
        "from tenacity import retry\n\n"
        "@retry\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='m', max_tokens=10, messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "decorated (@retry)" in site.form_reason


def test_a_called_decorator_is_not_routed_for_the_right_reason(tmp_path: Path) -> None:
    """It was already refused — by the rule about *body* calls, which is the
    wrong reason and the reason that missed the bare form."""
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n"
        "from tenacity import retry, stop_after_attempt\n\n"
        "@retry(stop=stop_after_attempt(5))\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='m', max_tokens=10, messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "decorated (@retry)" in site.form_reason


def test_kwargs_forwarded_into_the_sdk_call_are_not_routed(tmp_path: Path) -> None:
    """REPRODUCED: `**kwargs` is an `ast.keyword` with `arg=None` and was
    filtered out before any keyword was inspected, so the call looked thin and
    routed. A caller passing `stream=True` at runtime then defeats the stream
    check without touching the code migrate read.
    """
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p, **kwargs):\n"
        "    client = anthropic.Anthropic()\n"
        "    return client.messages.create(model='m', max_tokens=10, messages=[], **kwargs)\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "**kwargs" in site.form_reason
    assert "stream=" in site.form_reason


def test_a_client_constructed_with_arguments_is_not_routed(tmp_path: Path) -> None:
    """REPRODUCED with the corporate-gateway shape. `Services.model_provider`
    resolves its own endpoint and credential, so routing this call sends it to
    a different endpoint, on a different key, billed to a different account —
    and drops the SDK's own `max_retries` on the way.
    """
    _write(
        tmp_path,
        "svc.py",
        "import anthropic\n\n"
        "def ask(p):\n"
        "    client = anthropic.Anthropic(\n"
        "        base_url='https://llm-gateway.corp/v1', timeout=120.0, max_retries=8\n"
        "    )\n"
        "    return client.messages.create(model='m', max_tokens=10, messages=[])\n",
    )
    site = _only_site(tmp_path)
    assert not site.routed
    assert "configures its own client" in site.form_reason
    assert "base_url=" in site.form_reason and "max_retries=" in site.form_reason


def test_an_unconfigured_client_still_routes(tmp_path: Path) -> None:
    """The refusals above are not "refuse everything": the thin shape the ready
    loop measured must still route, or the increment they belong to is undone.
    """
    _write(tmp_path, "svc.py", THIN)
    assert _only_site(tmp_path).routed


# --------------------------------------------------------------------------
# ADR 0140 — --force must not discard an adopter's edits
# --------------------------------------------------------------------------


def test_force_backs_up_a_file_that_differs_before_overwriting(tmp_path: Path) -> None:
    """REPRODUCED: hand-edit the generated node body, run the `--force` line
    that `aef loop doctor`'s fix string prints, and the edits are gone — no
    backup, no diff, no warning, exit 0. This module's own comment calls an
    edited generated file "the expensive thing to lose".
    """
    from aef.cli.migrate import report

    _write(tmp_path, "svc.py", THIN)
    run_migrate(tmp_path)
    out = tmp_path / "aef_migrated.py"
    edited = out.read_text() + "\n# HAND EDIT: the system prompt, re-expressed\n"
    out.write_text(edited, encoding="utf-8")

    result = run_migrate(tmp_path, force=True)
    assert result.backup is not None, "an edited file must not be overwritten silently"
    assert result.backup.read_text() == edited
    assert "HAND EDIT" not in out.read_text()
    assert "backed up" in report(result)


def test_force_does_not_back_up_an_untouched_generated_file(tmp_path: Path) -> None:
    """A .bak per regeneration would be noise. Identical means nothing to lose."""
    _write(tmp_path, "svc.py", THIN)
    run_migrate(tmp_path)
    result = run_migrate(tmp_path, force=True)
    assert result.backup is None
    assert not list(tmp_path.glob("*.bak*"))


def test_a_second_force_does_not_destroy_the_first_backup(tmp_path: Path) -> None:
    """Losing the first round of edits to save the second is the same failure
    one step along."""
    _write(tmp_path, "svc.py", THIN)
    run_migrate(tmp_path)
    out = tmp_path / "aef_migrated.py"

    out.write_text(out.read_text() + "\n# EDIT ONE\n", encoding="utf-8")
    first = run_migrate(tmp_path, force=True)
    out.write_text(out.read_text() + "\n# EDIT TWO\n", encoding="utf-8")
    second = run_migrate(tmp_path, force=True)

    assert first.backup is not None and second.backup is not None
    assert first.backup != second.backup
    assert "EDIT ONE" in first.backup.read_text()
    assert "EDIT TWO" in second.backup.read_text()


# --------------------------------------------------------------------------
# ADR 0140 — a generated node that reaches a model is not pure
# --------------------------------------------------------------------------


def _built_node(tmp_path: Path, name: str, body: str) -> tuple[str, object]:
    import importlib.util

    root = tmp_path / name
    _write(root, "svc.py", body)
    out = root / "aef_migrated.py"
    source = render(scan(root), name)
    out.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"gen_{name}_effects", out)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    graph = module.build_graph()
    return source, graph.nodes[graph.entry_node]


def test_every_generated_node_declares_its_model_call_as_an_external_call(tmp_path: Path) -> None:
    """REPRODUCED: `render()` emitted `Node(...)` with no `side_effects`, so
    every generated node defaulted to `SideEffect.PURE` — a live model call
    declared to have no effect on the world, in both forms.
    """
    from aef.kernel import SideEffect
    from aef.state import AEFState

    for name, body in (("routed", THIN), ("unrouted", UNROUTABLE)):
        source, node = _built_node(tmp_path, name, body)
        assert "side_effects=SideEffect.EXTERNAL_CALL," in source, name
        assert node.side_effects is SideEffect.EXTERNAL_CALL, name
        assert node.idempotency_key_fn is not None, name
        key = node.idempotency_key_fn(AEFState(run_id="r1", agent_id="a", objective="o"))
        assert node.id in key and "r1" in key


def test_bounded_retry_engages_on_a_generated_node_instead_of_seeing_pure(tmp_path: Path) -> None:
    """The consequence of the PURE default, and the point of fixing it.

    `add_bounded_retry` reads the declaration from source before wrapping a
    node in a 3-attempt retry; its own comment says it "requires the
    declaration rather than assuming it". The generator never wrote one, so
    the guard asked a question nobody had answered and got the
    safest-sounding wrong answer — a live routed model call retried as pure.
    """
    from aef.harness.transformations import TransformationError, add_bounded_retry

    source, node = _built_node(tmp_path, "retryable", THIN)
    add_bounded_retry(source=source, failing_node=node.id, citation="run-1", attempts=3)

    # The declaration is what engages the guard: strip the key the generator
    # supplies and the same node is refused, rather than passing as pure.
    keyless = "\n".join(ln for ln in source.splitlines() if "idempotency_key_fn=" not in ln)
    try:
        add_bounded_retry(source=keyless, failing_node=node.id, citation="run-1", attempts=3)
    except TransformationError as exc:
        assert "idempotency_key_fn" in str(exc)
    else:  # pragma: no cover - the guard must refuse
        raise AssertionError("a non-pure node with no key must not be retried")


def test_a_long_node_id_keeps_the_generated_file_within_the_line_limit(tmp_path: Path) -> None:
    """Node ids come from the adopter's module paths, and the new
    `idempotency_key_fn=` line repeats the id. `src/services/llm/client.py`
    plus `call_llm_with_backend` is an ordinary shape and already 44
    characters; ADR 0137 records three E501s nobody had run ruff to find.
    """
    _ruff_the_generated_module(
        tmp_path,
        "src/services/llm/anthropic_backend_client.py",
        THIN.replace("def ask(", "def call_llm_with_backend_and_budget("),
    )
