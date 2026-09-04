"""The default `--agent-path` must name what `aef migrate` actually writes.

ADR 0149's F2. `aef/cli/loop.py` derived it as
`f"{DEFAULT_AGENT_ROOT}/demo/graph.py"` — the root came from `zones`, the
`demo` was spelled out, and `agents/demo/` is **aef-core's own fixture
directory**, which exists in no adopted repo. ADR 0147 claimed it had rebuilt
this constant from `DEFAULT_AGENT_ROOT`; it had rebuilt the root and kept the
`demo`. `aef/harness/loop.py::cycle` hardcoded the whole literal separately.

Reproduced on a repo that ran `adopt` then `migrate` and nothing else:
`aef loop doctor` reported three obligations unmet against a path that does
not exist and printed

    fix: aef loop bless --repo . --state loop-state --agent-path agents/demo/graph.py

which exits 1 with `no agent source at agents/demo/graph.py in HEAD`, and
`aef loop cycle` exited **0** with `no agent source at agents/demo/graph.py in
master: no candidate` — ADR 0139's signature "silently inert" failure, reached
from the documented defaults with nothing typed wrong.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aef.cli.migrate import DEFAULT_MIGRATED_OUT, run_migrate
from aef.harness.zones import DEFAULT_AGENT_PATH, DEFAULT_AGENT_ROOT

RAW_SDK_AGENT = """import anthropic


def run_agent(objective: str) -> str:
    client = anthropic.Anthropic()
    reply = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": objective}],
    )
    return reply.content[0].text
"""

AEF_ROOT = Path(__file__).resolve().parents[2] / "aef"

# The one place allowed to name a file under the agent root.
DERIVATION_SITE = (Path("aef") / "harness" / "zones.py", "DEFAULT_AGENT_PATH")


def test_the_default_agent_path_is_what_migrate_writes(tmp_path: Path) -> None:
    """Behavioural, and it is the whole defect: run the real `aef migrate` on a
    repo whose only agent is a raw-SDK call site, and the file it writes must
    be the file every `--agent-path` default points at."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "my_agent.py").write_text(RAW_SDK_AGENT)

    result = run_migrate(tmp_path, write=True)

    assert result.written is not None, "migrate wrote nothing to check the default against"
    assert result.out_relative == DEFAULT_AGENT_PATH, (
        f"migrate writes {result.out_relative!r} but every --agent-path default is "
        f"{DEFAULT_AGENT_PATH!r}; an adopted repo satisfies one of the two"
    )
    assert (tmp_path / DEFAULT_AGENT_PATH).is_file()
    # And the alias, so the two names cannot describe two strings again.
    assert DEFAULT_MIGRATED_OUT == DEFAULT_AGENT_PATH


def test_every_agent_path_default_is_the_one_constant() -> None:
    """Four CLI flags, `_warn_unmet_obligations`, and `harness.loop.cycle`'s
    keyword. One string behind all of them, or the CLI and the API disagree
    about which file the loop is looking at."""
    import argparse
    import inspect

    from aef.cli.loop import add_loop_parser
    from aef.harness.loop import cycle

    assert inspect.signature(cycle).parameters["agent_path"].default == DEFAULT_AGENT_PATH

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_loop_parser(subparsers)
    loop = subparsers.choices["loop"]
    loop_subs = next(
        action for action in loop._actions if isinstance(action, argparse._SubParsersAction)
    )
    seen = 0
    for name, sub in loop_subs.choices.items():
        for action in sub._actions:
            if "--agent-path" in action.option_strings:
                seen += 1
                assert action.default == DEFAULT_AGENT_PATH, (
                    f"`aef loop {name} --agent-path` defaults to {action.default!r}"
                )
    assert seen >= 4, f"only {seen} --agent-path flags found; the defaults moved"


def _renders_to_agent_file(node: ast.AST) -> str | None:
    """The string this expression denotes, if it names a FILE under the agent
    root — with `DEFAULT_AGENT_ROOT` substituted for its own value, because
    `f"{DEFAULT_AGENT_ROOT}/demo/graph.py"` is the exact form the defect took
    and a literal-only scan reads it as innocent.

    Returns `None` for anything that cannot be rendered — a bare name, a call,
    a path built at runtime. Aliasing the shared constant (`X =
    DEFAULT_AGENT_PATH`) is therefore allowed by construction, which is the
    pattern this test wants.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        rendered = node.value
    elif isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
                and value.value.id == "DEFAULT_AGENT_ROOT"
            ):
                parts.append(DEFAULT_AGENT_ROOT)
            else:
                return None
        rendered = "".join(parts)
    else:
        return None
    prefix = f"{DEFAULT_AGENT_ROOT}/"
    if rendered.startswith(prefix) and rendered.endswith(".py"):
        return rendered
    return None


def test_no_module_hardcodes_a_path_under_the_agent_root() -> None:
    """One derivation site, enforced.

    The failure was two constants for one fact — `zones`/`migrate` answering
    "where does the generated graph land?" and `cli/loop`+`harness/loop`
    answering "where is the agent?" — with only the first kept correct. This
    scans every module-level constant and every parameter default under
    `aef/` for a value that names a `.py` file under the agent root, whether
    spelled outright or interpolated from `DEFAULT_AGENT_ROOT`, and allows
    exactly one.

    Prose is deliberately out of scope: help text and generated documentation
    quote paths and globs by the dozen, and flagging those would make this
    test noise. What is scanned is what a caller SILENTLY GETS.
    """
    offenders: list[str] = []
    for path in sorted(AEF_ROOT.rglob("*.py")):
        rel = path.relative_to(AEF_ROOT.parent)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[tuple[str, ast.AST]] = []
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                targets += [(n, node.value) for n in names]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    targets.append((node.target.id, node.value))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                positional = args.posonlyargs + args.args
                pairs = list(
                    zip(
                        positional[len(positional) - len(args.defaults) :],
                        args.defaults,
                        strict=True,
                    )
                )
                pairs += [
                    (a, d)
                    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
                    if d is not None
                ]
                targets += [(f"{node.name}({a.arg}=)", d) for a, d in pairs]
            for name, value in targets:
                rendered = _renders_to_agent_file(value)
                if rendered is None:
                    continue
                if (rel, name) == DERIVATION_SITE:
                    continue
                offenders.append(f"{rel}:{name} = {rendered!r}")
    assert not offenders, (
        "a second default naming a file under the agent root has come back — derive it "
        f"from aef.harness.zones.DEFAULT_AGENT_PATH instead: {offenders}"
    )
