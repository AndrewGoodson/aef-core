"""`aef doctor` must open every graph the repo actually runs.

REPRODUCED before the fix, on a copy of the marlin pilot clone (8 personas
under `.claude/agents`, already `aef adopt`ed):

    $ aef migrate --dir <clone>
    wrote 8 prompt agent graph(s): agents/migrated/marlin_accela/graph.py ...
    $ find <clone> -name graph.py | wc -l
    9
    $ aef doctor --dir <clone> | grep model_calls
    [OK] model_calls_visible:aef_adapter.py: 1 reachable module(s), ...
    [OK] model_calls_visible:agents/migrated/graph.py: 1 reachable module(s), ...

Two entries against nine graphs, and obligation 6 — "every model call reaches
the harness" (ADR 0137) — passed on `agents/migrated/graph.py`, the call-site
stub whose `build_graph()` raises `NotImplementedError` and which makes no
model call at all. The eight graphs that DO call a model were never opened.

The cause is a seam, not a bug in either half: doctor globbed
`<agent root>/*/graph.py` (one level, ADR 0149's shape) and ADR 0152's
`aef migrate` writes `<agent root>/migrated/<module>/graph.py` (two). Both
halves were tested; neither test ran the producer into the consumer.

So the first test here does exactly that — the real `run_migrate` on a
prompt-file fixture, its own reported outputs asserted against the real
`_graph_entries` — which is the check the shared-constant argument in ADR
0149's docstring was standing in for, and could not make.
"""

from __future__ import annotations

from pathlib import Path

from aef.cli.doctor import _graph_entries, run_doctor
from aef.cli.migrate import LEGACY_MIGRATED_OUT, run_migrate
from aef.harness.zones import DEFAULT_AGENT_PATH, DEFAULT_AGENT_ROOT, discover_graph_files

PERSONA = """---
name: {name}
description: The {name} persona.
tools: Read, Write, Bash
---

# {name}

Never invent credentials.
"""

NAMES = ("pilot-accela", "pilot-azure", "pilot-source")


def _prompt_repo(root: Path) -> Path:
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for i, name in enumerate(NAMES):
        (agents / f"agent-{i}.md").write_text(PERSONA.format(name=name), encoding="utf-8")
    # A persona in a subdirectory, because discovery is recursive on both
    # sides and a flat walk on either would pass a flat fixture.
    nested = agents / "sub"
    nested.mkdir()
    (nested / "deep.md").write_text(PERSONA.format(name="pilot-deep"), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "util.py").write_text("def add(a: int) -> int:\n    return a\n", "utf-8")
    return root


def test_doctor_lists_every_graph_migrate_wrote(tmp_path: Path) -> None:
    """The C-to-D check: real producer into real consumer.

    `migrate` reports the graphs it wrote; every one of them must be in the
    list `doctor` scans. Asserted against migrate's OWN report rather than
    against a hardcoded depth, so a future change to migrate's layout fails
    here instead of silently shrinking what doctor opens.
    """
    result = run_migrate(_prompt_repo(tmp_path))
    assert result.prompt_agents, "fixture produced no prompt agents"

    entries = set(_graph_entries(tmp_path, None))
    written = {site.out_relative for site in result.prompt_agents}
    missing = sorted(written - entries)
    assert not missing, (
        f"migrate wrote {len(written)} graph(s) and doctor scans {len(entries)} entr(ies); "
        f"never opened: {missing}"
    )
    # And the call-site graph, which is a different writer at a different depth.
    assert result.out_relative in entries


def test_doctor_reports_a_model_call_check_for_each_of_them(tmp_path: Path) -> None:
    """End to end through the CLI-level function, because the list being right
    and the advisory firing are two different things — obligation 6 passing on
    a file nothing routes through is exactly what happened."""
    result = run_migrate(_prompt_repo(tmp_path))
    names = {c.name for c in run_doctor(tmp_path)}
    for site in result.prompt_agents:
        assert f"model_calls_visible:{site.out_relative}" in names, site.out_relative


def test_a_widened_agent_root_is_reported_on(tmp_path: Path) -> None:
    """`aef migrate --agent-root .claude/agents` puts the graphs beside the
    personas. Without `aef doctor --agent-root`, doctor reported on the two
    files OUTSIDE that root and said nothing about the ones inside it."""
    result = run_migrate(_prompt_repo(tmp_path), agent_root=".claude/agents")
    written = {site.out_relative for site in result.prompt_agents}
    assert all(p.startswith(".claude/agents/") for p in written), written

    default_entries = set(_graph_entries(tmp_path, None))
    assert not (written & default_entries), (
        "the default root should not reach into a widened one; if it does this "
        "test proves nothing about the flag"
    )

    widened = set(_graph_entries(tmp_path, None, ".claude/agents"))
    assert written <= widened, sorted(written - widened)
    # The call-site graph does NOT move with --agent-root, so widening must not
    # make it invisible either.
    assert DEFAULT_AGENT_PATH in widened


def test_an_explicit_agent_path_still_wins_outright(tmp_path: Path) -> None:
    """`--agent-path` means the owner has said which file it is; discovery is
    not additive to it."""
    run_migrate(_prompt_repo(tmp_path))
    assert _graph_entries(tmp_path, "some/other/graph.py") == ["some/other/graph.py"]


def test_discovery_keeps_the_pre_0143_path_and_the_adapter(tmp_path: Path) -> None:
    """Two entries that live outside the agent root and can only be named.

    Dropping `aef_migrated.py` would silently stop the model-call advisory
    firing in every repo migrated before ADR 0143.
    """
    (tmp_path / "aef_adapter.py").write_text("def build_graph() -> None: ...\n", "utf-8")
    (tmp_path / LEGACY_MIGRATED_OUT).write_text("def build_graph() -> None: ...\n", "utf-8")
    entries = discover_graph_files(tmp_path)
    assert entries[0] == "aef_adapter.py"
    assert LEGACY_MIGRATED_OUT in entries


def test_discovery_is_deduplicated_and_stable(tmp_path: Path) -> None:
    """`DEFAULT_AGENT_PATH` is both a named entry and reachable by the walk of
    the default root; it must appear once."""
    run_migrate(_prompt_repo(tmp_path))
    entries = discover_graph_files(tmp_path, agent_root=DEFAULT_AGENT_ROOT)
    assert len(entries) == len(set(entries)), entries
    assert entries == discover_graph_files(tmp_path, agent_root=DEFAULT_AGENT_ROOT)


def test_the_doctor_cli_takes_an_agent_root(tmp_path: Path) -> None:
    """The flag exists and reaches `run_doctor` — `aef doctor --agent-root
    .claude/agents` exited 2 with `unrecognized arguments` before this."""
    import argparse

    from aef.cli.main import build_parser

    parser: argparse.ArgumentParser = build_parser()
    args = parser.parse_args(["doctor", "--dir", str(tmp_path), "--agent-root", ".claude/agents"])
    assert args.agent_root == ".claude/agents"

    result = run_migrate(_prompt_repo(tmp_path), agent_root=".claude/agents")
    checks = run_doctor(tmp_path, agent_root=args.agent_root)
    names = {c.name for c in checks}
    for site in result.prompt_agents:
        assert f"model_calls_visible:{site.out_relative}" in names, site.out_relative
