"""`--agent-path` is one flag with two meanings, and both are answered.

`--proposer rule_based_prompt` reads it as the PERSONA `.md` it appends a
lesson to — its own help text says so, and ADR 0157's reproduced invocation
is exactly `--agent-path .claude/agents/accela-agent.md`. Preflight read the
same flag as a Python module. So on the documented prompt-proposer
invocation, `aef loop doctor` said:

    [--] reflect node routed to  no reflect node in the graph
         fix: add make_reflect_node() to your graph AND make a node
              `return delta, 'reflect'` — an Edge alone does not route
    [OK] model calls visible     1 graph scanned, none reaches a model SDK
                                 the harness cannot see
    EXIT=1

about a generated graph that routes correctly and had `import anthropic`
reachable from it. The fix line named an edit already made; the green line
was a clean bill of health over the planted fault. Every prompt-proposer
cycle printed the first one, forever (ADR 0178).

The end-to-end assertions here go through the REAL `aef migrate` into the
REAL `aef loop doctor` — the C<->D lesson (ADR 0167's F2), in the join where
the defect lived.
"""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from aef.cli.main import build_parser, main
from aef.cli.migrate import run_migrate


def _pilot(tmp_path: Path, *, agent_root: str = ".claude/agents") -> tuple[Path, list[object]]:
    root = tmp_path / "pilot"
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for name in ("accela", "azure"):
        (agents / f"{name}.md").write_text(
            f"---\nname: marlin-{name}\ndescription: d\n---\n\nbody\n", encoding="utf-8"
        )
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "client.py").write_text("import anthropic\n\nC = anthropic.Anthropic\n")
    result = run_migrate(root, agent_root=agent_root)
    assert result.prompt_agents, "migrate wrote no prompt-agent graph; the fixture is wrong"
    target = root / result.prompt_agents[0].out_relative
    target.write_text(target.read_text() + "\nfrom src.client import C  # noqa: E402,F401\n")
    return root, list(result.prompt_agents)


def _doctor(root: Path, tmp_path: Path, *args: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(
            [
                "loop",
                "doctor",
                "--repo",
                str(root),
                "--state",
                str(tmp_path / "state"),
                "--corpus",
                str(tmp_path / "corpus"),
                *args,
            ]
        )
    return code, buffer.getvalue()


def _line(out: str, name: str) -> str:
    return next(ln for ln in out.splitlines() if name in ln)


def test_the_documented_prompt_proposer_invocation_reports_on_the_generated_graph(
    tmp_path: Path,
) -> None:
    root, sites = _pilot(tmp_path)
    persona = sites[0].source  # type: ignore[attr-defined]
    graph = sites[0].out_relative  # type: ignore[attr-defined]

    code, out = _doctor(root, tmp_path, "--agent-root", ".claude/agents", "--agent-path", persona)

    reflect = _line(out, "reflect node routed to")
    assert "[OK]" in reflect, reflect
    assert graph in reflect, reflect
    assert "no reflect node" not in out

    visible = _line(out, "model calls visible")
    assert "[--]" in visible, visible
    assert "marlin_accela" in visible and "imports anthropic" in visible, visible
    assert code == 1


def test_a_persona_with_no_generated_graph_is_told_to_migrate(tmp_path: Path) -> None:
    root, sites = _pilot(tmp_path)
    persona = sites[0].source  # type: ignore[attr-defined]
    (root / sites[0].out_relative).unlink()  # type: ignore[attr-defined]

    _, out = _doctor(root, tmp_path, "--agent-root", ".claude/agents", "--agent-path", persona)
    reflect = _line(out, "reflect node routed to")
    assert "[--]" in reflect and "has no generated graph" in reflect, reflect
    assert "no reflect node" not in out
    assert "aef migrate" in out


def _agent_path_actions() -> dict[str, argparse.Action]:
    """Every `aef loop` subcommand carrying `--agent-path`, DERIVED.

    Named rather than remembered: four of the five had no help text at all,
    and a test naming the four would have been satisfied the day a fifth
    appeared (ADR 0167's M7 lesson)."""
    (outer,) = [
        a
        for a in build_parser()._actions
        if isinstance(a, argparse._SubParsersAction) and "loop" in a.choices
    ]
    (inner,) = [
        a for a in outer.choices["loop"]._actions if isinstance(a, argparse._SubParsersAction)
    ]
    found: dict[str, argparse.Action] = {}
    for name, parser in inner.choices.items():
        for action in parser._actions:
            if "--agent-path" in action.option_strings:
                found[name] = action
    return found


def test_every_loop_agent_path_argument_documents_both_forms() -> None:
    actions = _agent_path_actions()
    assert actions, "no --agent-path argument found; the derivation is broken"
    for name, action in actions.items():
        help_text = action.help or ""
        assert help_text.strip(), f"`loop {name} --agent-path` has no help text at all"
        assert "graph.py" in help_text, (name, help_text)
        assert "rule_based_prompt" in help_text, (name, help_text)
        assert ".md" in help_text, (name, help_text)


def test_the_proposer_help_and_the_agent_path_help_agree() -> None:
    """The persona form was documented only under `--proposer`, which is a
    different flag on a subset of the subcommands. Both must say it, or the
    reader who looks up the flag they are typing learns the wrong meaning."""
    actions = _agent_path_actions()
    (outer,) = [
        a
        for a in build_parser()._actions
        if isinstance(a, argparse._SubParsersAction) and "loop" in a.choices
    ]
    (inner,) = [
        a for a in outer.choices["loop"]._actions if isinstance(a, argparse._SubParsersAction)
    ]
    for name, parser in inner.choices.items():
        proposer = [a for a in parser._actions if "--proposer" in a.option_strings]
        if not proposer:
            continue
        assert "--agent-path" in (proposer[0].help or ""), name
        assert name in actions, f"`loop {name}` takes --proposer but not --agent-path"
