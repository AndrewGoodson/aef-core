"""`aef migrate` sees prompt-file agents, and says what it did to Zone A.

Reproduce-first, and the reproduction is a command that succeeded. On the
marlin pilot clone — a real repo with eight `.claude/agents/*.md` personas,
five skills, `AGENTS.md` and a `.codex/` — `aef migrate --dir .` printed

    scanned 38 Python file(s)
    found 0 call site(s): 0 wrapped, 0 skipped

exit 0, and wrote a graph whose `build_graph()` raises `NotImplementedError`.
Every eligible repo in the 2026-09-04 survey has zero SDK call sites, so that
was the answer for all of them: the scanner looks for functions wrapping a
vendor SDK, and their agents are markdown.

The first test here is that reproduction, run against a synthetic repo of the
same shape so CI keeps it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aef.cli.migrate import (
    discover_prompt_agents,
    discover_skills,
    render_prompt_agent,
    report,
    run_migrate,
)
from aef.harness.gates.g0_static_safety import scan_source
from aef.harness.zones import DEFAULT_AGENT_ROOT, Zone, ZonePolicy, inspect_path

AGENT_NAMES = (
    "marlin-accela",
    "marlin-azure",
    "marlin-bug-hunter",
    "marlin-implementer",
    "marlin-orchestrator",
    "marlin-reviewer",
    "marlin-security",
    "marlin-source",
)

PERSONA = """---
name: {name}
description: The {name} persona for the pilot repo.
tools: Read, Write, Bash
---

# {name}

Never invent credentials. Work only inside assigned paths.
"""


def _prompt_repo(root: Path, *, names: tuple[str, ...] = AGENT_NAMES, skills: int = 5) -> Path:
    """A repo shaped like the pilot: markdown agents, skills, no call site."""
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for i, name in enumerate(names):
        (agents / f"agent-{i}.md").write_text(PERSONA.format(name=name), encoding="utf-8")
    for i in range(skills):
        skill = root / ".claude" / "skills" / f"skill-{i}"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: skill-{i}\ndescription: does a thing\n---\n\nSee references/x.md.\n",
            encoding="utf-8",
        )
    src = root / "src"
    src.mkdir()
    (src / "util.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", "utf-8")
    return root


# ---------------------------------------------------------------------------
# The reproduction, and the fix
# ---------------------------------------------------------------------------
def test_a_prompt_file_repo_has_no_call_sites_and_that_is_still_true(tmp_path: Path) -> None:
    """The half of the old behaviour that was never wrong: there is no Python
    here wrapping a vendor SDK, and the scanner must keep saying so."""
    result = run_migrate(_prompt_repo(tmp_path), write=False)
    assert result.total_found == 0
    assert "found 0 call site(s)" in report(result)


def test_migrate_finds_every_prompt_agent_and_writes_one_graph_each(tmp_path: Path) -> None:
    result = run_migrate(_prompt_repo(tmp_path))
    assert len(result.prompt_agents) == 8, [s.definition.name for s in result.prompt_agents]
    assert [s.definition.name for s in result.prompt_agents] == sorted(AGENT_NAMES)
    assert len(result.prompt_written) == 8
    for site in result.prompt_agents:
        assert (tmp_path / site.out_relative).is_file(), site.out_relative


def test_one_graph_per_agent_never_several_agents_in_one_graph(tmp_path: Path) -> None:
    """F6's lesson (ADR 0149): three call sites in one generated graph left two
    nodes declared, routed and unreachable, and nothing warned. One agent per
    graph makes that shape impossible to produce here."""
    result = run_migrate(_prompt_repo(tmp_path))
    outs = {site.out_relative for site in result.prompt_agents}
    assert len(outs) == 8
    for site in result.prompt_agents:
        source = (tmp_path / site.out_relative).read_text(encoding="utf-8")
        assert source.count("make_prompt_agent_node(") == 1
        assert source.count("AGENT_FILE = ") == 1
        assert source.count("entry_node=") == 1


def test_the_graph_id_is_the_agent_name_and_the_module_is_importable(tmp_path: Path) -> None:
    result = run_migrate(_prompt_repo(tmp_path))
    site = next(s for s in result.prompt_agents if s.definition.name == "marlin-bug-hunter")
    assert site.graph_id == "marlin-bug-hunter"
    assert site.module == "marlin_bug_hunter".replace("-", "_")
    assert site.dotted == f"{DEFAULT_AGENT_ROOT}.migrated.marlin_bug_hunter.graph"
    assert all(part.isidentifier() for part in site.dotted.split("."))


def test_a_name_that_is_not_a_module_is_made_into_one(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("2fa checker", "class", "Ops/Team!"))
    sites = discover_prompt_agents(root)
    modules = [s.module for s in sites]
    assert all(m.isidentifier() for m in modules), modules
    assert len(set(modules)) == 3


def test_two_names_that_sanitise_alike_do_not_overwrite_each_other(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("ops-team", "ops team"))
    sites = discover_prompt_agents(root)
    assert len({s.out_relative for s in sites}) == 2, [s.out_relative for s in sites]


def test_subdirectories_are_searched_because_the_cli_searches_them(tmp_path: Path) -> None:
    """Measured, not assumed: a scratch repo holding `.claude/agents/probe-one.md`
    and `.claude/agents/sub/probe-two.md` had `claude -p --agent <unknown>` list
    BOTH in its rejection (which is issued before any model call). A flat glob
    would migrate some of an adopter's agents and leave the organised ones."""
    root = _prompt_repo(tmp_path, names=("flat-one",))
    nested = root / ".claude" / "agents" / "sub"
    nested.mkdir()
    (nested / "deep.md").write_text(PERSONA.format(name="deep-one"), encoding="utf-8")
    names = {s.definition.name for s in discover_prompt_agents(root)}
    assert names == {"flat-one", "deep-one"}


def test_migrate_does_not_read_its_own_output_on_a_second_run(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("one",))
    run_migrate(root, agent_root=".claude/agents")
    again = run_migrate(root, agent_root=".claude/agents", force=True)
    assert [s.definition.name for s in again.prompt_agents] == ["one"]


# ---------------------------------------------------------------------------
# What the generated graph is
# ---------------------------------------------------------------------------
def test_the_generated_graph_builds_and_is_wired_to_reflect(tmp_path: Path) -> None:
    import importlib.util

    result = run_migrate(_prompt_repo(tmp_path, names=("marlin-accela",)))
    out = tmp_path / result.prompt_agents[0].out_relative
    spec = importlib.util.spec_from_file_location("gen_prompt_agent", out)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    graph = module.build_graph()

    assert graph.id == "marlin-accela"
    assert graph.entry_node == "prompt_agent"
    assert set(graph.nodes) == {"prompt_agent", "reflect", "consolidate"}
    # The tail is what makes the repo learn (ADR 0139/0143): route the first
    # node to END instead and `aef loop cycle` exits 0 forever with
    # `no admissible failure memory`.
    assert {(e.from_node, e.to_node) for e in graph.edges} == {
        ("prompt_agent", "reflect"),
        ("reflect", "consolidate"),
    }
    graph.compile()


def test_the_generated_graph_passes_g0s_own_static_scan(tmp_path: Path) -> None:
    """It lands in Zone A, so the gate that judges agent-authored code will
    read it. A generated file its own gate rejects is a trap, not a feature —
    and G0's allowlist has no `pathlib`, no `hashlib`, no `os`."""
    result = run_migrate(_prompt_repo(tmp_path, names=("marlin-accela",)))
    rel = result.prompt_agents[0].out_relative
    findings = scan_source(rel, (tmp_path / rel).read_text(encoding="utf-8"))
    assert findings == (), [str(f) for f in findings]


def test_the_generated_graph_passes_the_repos_own_ruff(tmp_path: Path) -> None:
    result = run_migrate(_prompt_repo(tmp_path))
    paths = [str(tmp_path / s.out_relative) for s in result.prompt_agents]
    check = subprocess.run(
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
            *paths,
        ],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    fmt = subprocess.run(
        ["ruff", "format", "--check", "--isolated", "--line-length", "100", *paths],
        capture_output=True,
        text=True,
    )
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr


def test_the_generated_graph_names_the_persona_and_does_not_copy_it(tmp_path: Path) -> None:
    """Reading at execution time is what makes the Zone A widening worth
    anything: a proposer edits the `.md` and the next run sends it."""
    result = run_migrate(_prompt_repo(tmp_path, names=("marlin-accela",)))
    site = result.prompt_agents[0]
    source = (tmp_path / site.out_relative).read_text(encoding="utf-8")
    assert site.source in source
    assert "Never invent credentials" not in source


def test_the_generated_graph_states_the_safety_property(tmp_path: Path) -> None:
    result = run_migrate(_prompt_repo(tmp_path, names=("marlin-accela",)))
    source = (tmp_path / result.prompt_agents[0].out_relative).read_text(encoding="utf-8")
    assert "THE PROMPT RUNS; THE AGENT'S TOOLS DO NOT" in source
    assert "--tools" in source


def test_frontmatter_capabilities_are_named_in_the_generated_file(tmp_path: Path) -> None:
    result = run_migrate(_prompt_repo(tmp_path, names=("marlin-accela",)))
    site = result.prompt_agents[0]
    assert "tools" in site.definition.unhonoured_keys
    source = render_prompt_agent(site, "marlin")
    assert "NOT acted on" in source and "`tools`" in source


def test_an_existing_graph_is_never_overwritten_without_force(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("one",))
    first = run_migrate(root)
    target = root / first.prompt_agents[0].out_relative
    target.write_text("# hand edited\n", encoding="utf-8")

    second = run_migrate(root)
    assert second.prompt_written == []
    assert second.prompt_existing == [first.prompt_agents[0].out_relative]
    assert target.read_text(encoding="utf-8") == "# hand edited\n"

    third = run_migrate(root, force=True)
    assert len(third.prompt_written) == 1
    assert "hand edited" not in target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Zone A, and what the report says about it
# ---------------------------------------------------------------------------
def test_by_default_the_persona_is_not_zone_a_and_the_report_says_so(tmp_path: Path) -> None:
    """Widening Zone A is a scope decision, not a default. The default tree is
    unchanged, so the loop may improve the generated GRAPH and never the
    PROMPT — and the adopter is told that at the moment of writing rather than
    at the end of a cycle."""
    result = run_migrate(_prompt_repo(tmp_path))
    site = result.prompt_agents[0]
    assert site.out_relative.startswith(f"{DEFAULT_AGENT_ROOT}/")
    assert inspect_path(site.out_relative).zone is Zone.A
    assert inspect_path(site.source).zone is Zone.C

    text = report(result)
    assert "BLAST RADIUS" in text
    assert "The PERSONA FILES are NOT" in text
    assert "--agent-root .claude/agents" in text


def test_the_opt_in_root_puts_the_persona_inside_zone_a(tmp_path: Path) -> None:
    result = run_migrate(_prompt_repo(tmp_path), agent_root=".claude/agents")
    policy = ZonePolicy(agent_root=".claude/agents")
    site = result.prompt_agents[0]
    assert site.out_relative.startswith(".claude/agents/migrated/")
    assert inspect_path(site.source, policy).zone is Zone.A
    assert inspect_path(site.out_relative, policy).zone is Zone.A
    # Defence in depth is untouched: no agent root swallows the harness.
    assert inspect_path("aef/harness/gates/g0_static_safety.py", policy).zone is Zone.B

    text = report(result)
    assert "The PERSONA FILES are inside it too" in text
    assert "Pass the SAME --agent-root" in text


def test_the_default_call_site_output_is_unchanged_by_all_of_this(tmp_path: Path) -> None:
    """ADR 0149's F2 constant. A prompt-file repo must not move the file every
    `--agent-path` default points at."""
    from aef.harness.zones import DEFAULT_AGENT_PATH

    result = run_migrate(_prompt_repo(tmp_path))
    assert result.out_relative == DEFAULT_AGENT_PATH
    assert (tmp_path / DEFAULT_AGENT_PATH).is_file()


# ---------------------------------------------------------------------------
# Skills: found, named, and deliberately not migrated
# ---------------------------------------------------------------------------
def test_skills_are_found_and_not_migrated(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("one",), skills=5)
    result = run_migrate(root)
    assert len(result.skills_seen) == 5
    assert len(result.prompt_agents) == 1, "a skill was migrated as an agent"
    text = report(result)
    assert "did NOT migrate any of them" in text
    assert "A skill is not an agent" in text
    for path in result.skills_seen:
        assert path in text


def test_a_skills_own_test_fixtures_are_not_counted_as_skills(tmp_path: Path) -> None:
    """`rglob` reported ten on the pilot where there are six: two `SKILL.md`
    files lived inside one skill's own fixture corpus. The convention is one
    `SKILL.md` per top-level skill directory, and the report's first number has
    to be right about the repo it describes."""
    root = _prompt_repo(tmp_path, names=("one",), skills=2)
    nested = root / ".claude" / "skills" / "skill-0" / "fixtures" / "inner"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("---\nname: fixture\n---\n\nx\n", encoding="utf-8")
    assert len(discover_skills(root)) == 2


def test_a_repo_with_no_prompt_agents_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.py").write_text("x = 1\n", encoding="utf-8")
    result = run_migrate(tmp_path)
    assert result.prompt_agents == []
    assert result.skills_seen == []
    text = report(result)
    assert "found 0 prompt agent(s)" in text
    assert "BLAST RADIUS" not in text
