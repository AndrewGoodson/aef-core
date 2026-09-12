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

import json
import os
import runpy
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from aef.cli.migrate import (
    discover_adopter_skills,
    discover_prompt_agents,
    discover_skills,
    render_prompt_agent,
    report,
    run_migrate,
    scan,
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


def test_native_harness_agents_are_discovered_without_granting_tools(tmp_path: Path) -> None:
    for harness in ("claude", "grok"):
        path = tmp_path / f".{harness}/agents/reviewer.md"
        path.parent.mkdir(parents=True)
        path.write_text(PERSONA.format(name="reviewer"))
    codex = tmp_path / ".codex/agents/reviewer.toml"
    codex.parent.mkdir(parents=True)
    codex.write_text(
        'name = "reviewer"\ndescription = "Review"\n'
        'developer_instructions = "Use supplied evidence."\n'
        'sandbox_mode = "danger-full-access"\n'
    )
    sites = discover_prompt_agents(tmp_path)
    assert len(sites) == 3
    assert len({site.out_relative for site in sites}) == 3
    assert len({site.graph_id for site in sites}) == 3
    definition = next(site.definition for site in sites if site.source.endswith(".toml"))
    assert definition.body == "Use supplied evidence."
    assert definition.unhonoured_keys == ("sandbox_mode",)
    for site in sites:
        compile(render_prompt_agent(site, "fixture"), site.out_relative, "exec")


def test_disambiguation_reserves_existing_suffixes(tmp_path: Path) -> None:
    base = tmp_path / ".claude/agents"
    base.mkdir(parents=True)
    for i, name in enumerate(("a", "a", "a_2")):
        (base / f"{i}.md").write_text(PERSONA.format(name=name))
    sites = discover_prompt_agents(tmp_path)
    assert len({site.out_relative for site in sites}) == 3
    assert len({site.graph_id for site in sites}) == 3


@pytest.mark.parametrize("old_harness", ["claude", "grok"])
def test_adding_a_colliding_persona_preserves_prior_graph_identity(
    tmp_path: Path, old_harness: str
) -> None:
    original = tmp_path / f".{old_harness}/agents/z.md"
    original.parent.mkdir(parents=True)
    original.write_text(PERSONA.format(name="reviewer"))
    first = run_migrate(tmp_path)
    old_site = first.prompt_agents[0]
    old_bytes = (tmp_path / old_site.out_relative).read_bytes()

    added = tmp_path / ".claude/agents/a.md"
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text(PERSONA.format(name="reviewer"))
    second = run_migrate(tmp_path)
    assert len(second.prompt_written) == 1
    sites = {site.source: site for site in second.prompt_agents}
    assert sites[old_site.source].out_relative == old_site.out_relative
    assert sites[old_site.source].graph_id == old_site.graph_id
    assert (tmp_path / old_site.out_relative).read_bytes() == old_bytes
    for site in sites.values():
        namespace = runpy.run_path(str(tmp_path / site.out_relative))
        assert namespace["AGENT_FILE"] == site.source
        assert namespace["build_graph"]().id == site.graph_id
    assert len({site.graph_id for site in sites.values()}) == 2
    assert run_migrate(tmp_path).prompt_written == []


def test_prior_duplicate_graph_does_not_steal_a_new_persona(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("reviewer",), skills=0)
    original = run_migrate(root).prompt_agents[0]
    duplicate = replace(
        original,
        module="reviewer_2",
        out_relative="agents/migrated/reviewer_2/graph.py",
        graph_id_override="reviewer_2",
    )
    duplicate_path = root / duplicate.out_relative
    duplicate_path.parent.mkdir()
    duplicate_bytes = render_prompt_agent(duplicate, root.name).encode()
    duplicate_path.write_bytes(duplicate_bytes)
    (root / ".claude/agents/a.md").write_text(PERSONA.format(name="reviewer"))
    result = run_migrate(root)
    added = next(site for site in result.prompt_agents if site.source.endswith("/a.md"))
    assert runpy.run_path(str(root / added.out_relative))["AGENT_FILE"] == added.source
    assert duplicate_path.read_bytes() == duplicate_bytes


def test_prior_graph_identity_is_read_without_executing_owner_code(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("reviewer",), skills=0)
    original = run_migrate(root).prompt_agents[0]
    graph = root / original.out_relative
    content = graph.read_bytes() + b"\nraise RuntimeError('do not import owner code')\n"
    graph.write_bytes(content)
    (root / ".claude/agents/a.md").write_text(PERSONA.format(name="reviewer"))
    result = run_migrate(root)
    retained = next(site for site in result.prompt_agents if site.source == original.source)
    assert retained.out_relative == original.out_relative
    assert graph.read_bytes() == content


def test_sdk_scan_prunes_excluded_trees_before_visiting_them(tmp_path: Path) -> None:
    excluded = tmp_path / ".venv/large/nested"
    excluded.mkdir(parents=True)
    (excluded / "vendor.py").write_text("raise RuntimeError('not project code')")
    (tmp_path / "owned.py").write_text("def owned(): return 1")
    # A subprocess confines the audit hook to this check. Watching the public
    # filesystem event works for both pathlib's cached scandir and os.walk.
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json, sys\n"
            "from pathlib import Path\n"
            "from aef.cli.migrate import scan\n"
            "visited = []\n"
            "sys.addaudithook(lambda event, args: "
            "visited.append(str(args[0])) if event == 'os.scandir' else None)\n"
            "result = scan(Path(sys.argv[1]))\n"
            "print(json.dumps([result.scanned_files, visited]))\n",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    scanned, paths = json.loads(result.stdout)
    visited = [Path(path) for path in paths]
    assert scanned == 1
    assert visited
    assert not any(path.is_relative_to(tmp_path / ".venv") for path in visited)


def test_sdk_scan_does_not_follow_python_file_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "private.txt"
    outside.write_text(
        "def hidden():\n"
        "    import anthropic\n"
        "    return anthropic.Anthropic().messages.create(model='x', messages=[])\n"
    )
    (tmp_path / "linked.py").symlink_to(outside)
    result = scan(tmp_path)
    assert result.sites == []
    assert any("symlink" in item.reason for item in result.skipped)


def test_discovery_refuses_symlinked_personas(tmp_path: Path) -> None:
    from aef.reasoning.prompt_agent import PromptAgentError

    outside = tmp_path / "private.md"
    outside.write_text("Private material")
    base = tmp_path / ".grok/agents"
    base.mkdir(parents=True)
    (base / "linked.md").symlink_to(outside)
    with pytest.raises(PromptAgentError, match="symlink"):
        discover_prompt_agents(tmp_path)


@pytest.mark.parametrize(
    "relative", [".claude/agents/pipe.md", ".codex/agents/pipe.toml", ".grok/agents/pipe.md"]
)
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX named pipes")
def test_discovery_refuses_nonregular_personas_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    from aef.reasoning.prompt_agent import PromptAgentError

    pipe = tmp_path / relative
    pipe.parent.mkdir(parents=True)
    os.mkfifo(pipe)

    def must_not_load(*args: object, **kwargs: object) -> None:
        raise AssertionError("discovery attempted to read a named pipe")

    monkeypatch.setattr("aef.cli.migrate.load_agent_file", must_not_load)
    with pytest.raises(PromptAgentError, match="nonregular agent file"):
        discover_prompt_agents(tmp_path)


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
    # `retrieve`, not `prompt_agent`. The head is what makes the repo USE what
    # it learned (ADR 0179, R6): without it `state.retrieved_context` is empty
    # on every adopter run, so no lesson is ever in front of the model and
    # `retrieved_signatures` is `[]` on every record forever — the tally ADR
    # 0118 records becomes a constant.
    assert graph.entry_node == "retrieve"
    assert set(graph.nodes) == {"retrieve", "prompt_agent", "reflect", "consolidate"}
    # The tail is what makes the repo learn (ADR 0139/0143): route the first
    # node to END instead and `aef loop cycle` exits 0 forever with
    # `no admissible failure memory`.
    assert {(e.from_node, e.to_node) for e in graph.edges} == {
        ("retrieve", "prompt_agent"),
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
    """The containment claim is CONDITIONED on the impl, and says so (ADR 0169).

    This test replaces one that asserted the unconditional sentence, and that
    is the point: `aef migrate` stamped "THE PROMPT RUNS; THE AGENT'S TOOLS DO
    NOT ... the harness adapters send `--tools ""` with `--max-turns 1`" into
    every generated module as fact, while `codex` sends neither flag, `grok`'s
    `--tools ""` was measured to suppress nothing, and `command` sends
    whatever an owner's template says. A test pinning the old sentence would
    have defended it through this fix, so it is replaced deliberately rather
    than extended.
    """
    result = run_migrate(_prompt_repo(tmp_path, names=("marlin-accela",)))
    source = (tmp_path / result.prompt_agents[0].out_relative).read_text(encoding="utf-8")

    # The unconditional claim must not come back. Put it back -> this fails.
    assert "THE PROMPT RUNS; THE AGENT'S TOOLS DO NOT" not in source
    assert "touches nothing" not in source

    assert "CONTAINMENT DEPENDS ON `model_provider.impl`" in source
    # Every impl the runtime can be pointed at is named with what it enforces.
    for impl in ("claude_code", "grok", "codex", "command", "anthropic"):
        assert impl in source, f"the generated header does not say what {impl} enforces"
    assert "--tools" in source
    assert "MEASURED to suppress nothing" in source, "grok's finding must survive generation"
    assert "nothing that suppresses tools" in source, "codex's weaker isolation must be named"
    assert "YOUR assertion, recorded unverified" in source, "command's assertion must be named"
    # And where a reader finds the per-run evidence instead of this comment.
    assert 'working_memory["prompt_agent__containment"]' in source
    assert "prompt_agent.persona_in_user_turn" in source


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


def test_forcing_prompt_graph_updates_preserves_each_edited_version(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("reviewer",), skills=0)
    first = run_migrate(root)
    out = first.prompt_written[0]
    # Owner code may use a non-UTF-8 encoding. A backup must preserve bytes.
    edited = b"# coding: latin-1\r\n# owner caf\xe9\r\n"
    out.write_bytes(edited)
    second = run_migrate(root, force=True)
    backup = out.with_suffix(".py.bak")
    assert backup.read_bytes() == edited
    assert str(backup) in report(second)
    out.write_bytes(b"# second edit\n")
    third = run_migrate(root, force=True)
    assert backup.read_bytes() == edited
    assert out.with_suffix(".py.bak.1").read_bytes() == b"# second edit\n"
    assert str(out.with_suffix(".py.bak.1")) in report(third)


def test_forcing_unchanged_prompt_graph_does_not_create_backup(tmp_path: Path) -> None:
    root = _prompt_repo(tmp_path, names=("reviewer",), skills=0)
    first = run_migrate(root)
    run_migrate(root, force=True)
    assert not list(first.prompt_written[0].parent.glob("*.bak*"))


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


# ---------------------------------------------------------------------------
# ADR 0168 / F5 — the report contradicted itself under a widened agent root
#
# REPRODUCED, one command, two sentences twelve lines apart:
#
#     $ aef migrate --dir <clone> --agent-root .claude/agents
#     wrote .../agents/migrated/graph.py
#       Zone A (agents/**) - agent-writable, the only tree the self-rewiring
#       loop may propose changes to
#     ...
#     BLAST RADIUS - what the self-rewiring loop may now propose changes to.
#       Zone A is '.claude/agents'. The generated graphs are inside it.
#
# and the classifier the gates use agreeing with neither:
#
#     >>> inspect_path("agents/migrated/graph.py",
#     ...              ZonePolicy(agent_root=".claude/agents")).zone
#     Zone.C
#
# `_zone_note` classified with the DEFAULT `ZonePolicy` and hardcoded
# `DEFAULT_AGENT_ROOT` in its own string; `result.agent_root` never reached it.
# ---------------------------------------------------------------------------
def test_the_zone_note_reports_the_zone_under_the_root_the_loop_will_run(
    tmp_path: Path,
) -> None:
    """The note and the gate must agree, under BOTH roots. Asserted against
    `inspect_path` itself rather than against a phrase, so the test cannot
    drift away from the classifier the way the string did."""
    for agent_root in (DEFAULT_AGENT_ROOT, ".claude/agents"):
        root = _prompt_repo(tmp_path / agent_root.replace("/", "_"), names=("one",))
        result = run_migrate(root, agent_root=agent_root)
        assert result.out_relative is not None
        policy = ZonePolicy(agent_root=agent_root)
        zone = inspect_path(result.out_relative, policy).zone
        text = report(result)
        if zone is Zone.A:
            assert f"Zone A ({agent_root}/**)" in text, text
            assert "Zone C under the agent root" not in text
        else:
            assert f"Zone C under the agent root this run used ({agent_root!r})" in text, text
            assert f"Zone A ({agent_root}/**)" not in text


def test_the_report_never_claims_zone_a_for_a_file_the_gate_calls_zone_c(
    tmp_path: Path,
) -> None:
    """The contradiction itself, stated as the invariant: no line of the report
    may say `Zone A (agents/**)` about a run whose Zone A is somewhere else."""
    result = run_migrate(_prompt_repo(tmp_path, names=("one",)), agent_root=".claude/agents")
    text = report(result)
    assert "Zone A (agents/**)" not in text, (
        "the per-file note still classifies with the default policy while BLAST "
        f"RADIUS says Zone A is {result.agent_root!r}"
    )
    assert "Zone A is '.claude/agents'" in text


def test_the_widened_note_names_the_agent_paths_that_are_inside_the_root(
    tmp_path: Path,
) -> None:
    """The next command the operator types takes one of these. `--agent-root`
    moves the prompt-agent graphs; `--out` moves the call-site graph, so it
    landing outside a widened root is ordinary rather than a mistake - and the
    note has to say which paths ARE inside."""
    result = run_migrate(_prompt_repo(tmp_path), agent_root=".claude/agents")
    text = report(result)
    assert "`--agent-root` moves the PROMPT AGENT graphs, `--out` moves this one" in text
    for site in result.prompt_agents:
        assert f"--agent-path {site.out_relative}" in text, site.out_relative
    assert "The CALL-SITE graph is NOT (agents/migrated/graph.py is Zone C)" in text


# ---------------------------------------------------------------------------
# ADR 0168 / S2 — a persona name is not a path segment
#
# REPRODUCED. `.claude/agents/evil.md` with `name: ../escape`:
#
#     AGENT    ../escape  (.claude/agents/evil.md)
#               -> agents/migrated/escape/graph.py
#               graph_id='../escape', wired prompt_agent -> ...
#
# The MODULE was sanitised; the graph id was not, and the report prints it as
# the value to hand `aef loop bless --graph-id`. `archive._graph_dir` is
# `root / graph_id`, so that id wrote `state/escape/v000001/` - one level above
# the archive root, which was left empty.
# ---------------------------------------------------------------------------
def test_a_persona_name_that_is_not_a_path_segment_never_becomes_a_graph_id(
    tmp_path: Path,
) -> None:
    from aef.harness.zones import segment_refusal

    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    for i, name in enumerate(("../escape", "a/b", "/absolute", "ok-name")):
        (agents / f"agent-{i}.md").write_text(PERSONA.format(name=name), encoding="utf-8")

    result = run_migrate(tmp_path)
    by_name = {site.definition.name: site for site in result.prompt_agents}
    assert set(by_name) == {"../escape", "a/b", "/absolute", "ok-name"}

    for name, site in by_name.items():
        assert not segment_refusal(site.graph_id), (
            f"graph_id {site.graph_id!r} (from persona {name!r}) is still not a "
            f"single safe path segment"
        )
    assert by_name["ok-name"].graph_id == "ok-name", "a safe name must be left alone"
    assert by_name["../escape"].graph_id == by_name["../escape"].module


def test_a_refused_persona_name_is_named_in_the_report_never_silently_renamed(
    tmp_path: Path,
) -> None:
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "evil.md").write_text(PERSONA.format(name="../escape"), encoding="utf-8")

    result = run_migrate(tmp_path)
    text = report(result)
    assert "NAME REFUSED as a graph id" in text, text
    assert "path traversal" in text
    assert "graph_id='escape'" in text
    # The persona's own name is still shown, so the line can be traced to a file.
    assert "AGENT    ../escape" in text


def test_the_generated_module_uses_the_safe_id_and_keeps_the_persona_name(
    tmp_path: Path,
) -> None:
    """`Graph(id=...)` is what reaches the archive; `agent_name` is what the
    model is told it is. Only the first has to be a path segment."""
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "evil.md").write_text(PERSONA.format(name="../escape"), encoding="utf-8")

    result = run_migrate(tmp_path)
    (site,) = result.prompt_agents
    source = (tmp_path / site.out_relative).read_text(encoding="utf-8")
    assert 'GRAPH_ID = "escape"' in source, source
    assert 'AGENT_NAME = "../escape"' in source
    assert "id=GRAPH_ID," in source
    assert "agent_name=AGENT_NAME," in source


# ---------------------------------------------------------------------------
# ADR 0168 / M4 — the report printed a command that cannot run
#
# REPRODUCED, from the repo `aef migrate --agent-root .claude/agents` produced:
#
#     $ aef run .claude.agents.migrated.marlin_accela.graph --objective x --config aef.yaml
#     error: the 'package' argument is required to perform a relative import
#     for '.claude.agents.migrated.marlin_accela.graph'
#
# A leading dot is a relative import to `importlib`, and no dotted spelling of
# `.claude/agents/...` exists at all. M1 shipped a flag whose own generated
# command could not be run under it.
# ---------------------------------------------------------------------------
COMMAND_PROVIDER_CONFIG = """model_provider:
  impl: command
  model: stub
  command:
    argv: ["/bin/echo", "{prompt}"]
    output: stdout
memory:
  impl: in_memory
objectives: exercise the generated graph
"""


def _printed_run_command(text: str, out_relative: str) -> str:
    """The `aef run ...` line the report prints for one agent."""
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.strip() == f"-> {out_relative}")
    return next(
        line.strip().removeprefix("-> ")
        for line in lines[index + 1 :]
        if line.strip().startswith("-> aef run ")
    )


def test_the_printed_run_command_parses_and_runs_under_a_widened_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real producer, real parser, real runner — no live model call.

    The whole defect was that nothing ever fed migrate's own printed command
    back into the CLI that has to accept it.

    Run from the repo root, which is what the printed command assumes and what
    `aef run` has always documented — the dotted form needs the same thing (it
    is `_ensure_cwd_importable` that puts the CWD on `sys.path`), so the file
    form adds no requirement the adopter did not already have.
    """
    import shlex

    from aef.cli.main import build_parser
    from aef.cli.run import run_graph_module

    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=0)
    (root / "aef.yaml").write_text(COMMAND_PROVIDER_CONFIG, encoding="utf-8")
    result = run_migrate(root, agent_root=".claude/agents")
    (site,) = result.prompt_agents
    assert site.out_relative.startswith(".claude/agents/"), site.out_relative

    command = _printed_run_command(report(result), site.out_relative)
    argv = shlex.split(command)
    assert argv[0] == "aef" and argv[1] == "run"

    # 1. the REAL parser accepts it
    args = build_parser().parse_args(argv[1:])
    assert args.module == site.out_relative, (
        f"the report printed {args.module!r}, which is not the file that was written"
    )

    # 2. and the REAL runner runs it, with a local `echo` as the provider
    monkeypatch.chdir(root)
    state = run_graph_module(
        args.module,
        agent_id="a1",
        objective="what are the preconditions?",
        config_path=root / "aef.yaml",
    )
    assert "prompt_agent" in state.working_memory, state.working_memory
    assert "what are the preconditions?" in str(state.working_memory["prompt_agent"])


def test_the_dotted_form_is_still_printed_when_it_is_importable(tmp_path: Path) -> None:
    """The control. Under the default root the dotted name works and is what an
    adopter expects to see; the file path is the fallback, not the new normal."""
    result = run_migrate(_prompt_repo(tmp_path, names=("pilot-accela",), skills=0))
    (site,) = result.prompt_agents
    assert site.importable
    assert site.run_target == site.dotted == f"{DEFAULT_AGENT_ROOT}.migrated.pilot_accela.graph"
    text = report(result)
    assert f"aef run {site.dotted} " in text
    assert "a file path, not" not in text


def test_a_non_importable_root_is_named_in_the_report(tmp_path: Path) -> None:
    result = run_migrate(
        _prompt_repo(tmp_path, names=("pilot-accela",), skills=0), agent_root=".claude/agents"
    )
    (site,) = result.prompt_agents
    assert not site.importable
    assert site.run_target == site.out_relative
    text = report(result)
    assert f"aef run {site.out_relative} " in text
    assert "a file path, not '.claude.agents.migrated.pilot_accela.graph'" in text


# ---------------------------------------------------------------------------
# R6 — the retrieval wire reaches the generated graph (ADR 0179)
# ---------------------------------------------------------------------------
def test_a_consolidated_lesson_reaches_the_generated_graphs_user_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduction, end to end, through the REAL `run_migrate` and the
    REAL runner. `render_retrieved_context` had exactly one caller —
    `agents/summary/graph.py`, this repo's own fixture, which ships in no
    adopted repo — and the generated template was `prompt_agent -> reflect ->
    consolidate -> END` with no retrieve node. So on every adopter run
    `state.retrieved_context` was `[]`, `retrieved_signatures` was `[]` on
    every reflection record, and ADR 0157's rationale printed `helpful 0 /
    harmful 0` as a constant. Reproduced: three runs, `retrieved_context=[]`
    each time, one entry formed, tallies 0/0.

    `/bin/echo {prompt}` makes the answer the user turn verbatim, so this
    reads the actual request rather than a proxy for it."""
    from datetime import UTC, datetime

    from aef.cli.run import run_graph_module
    from aef.harness.memory_store import FileMemoryStore
    from aef.services.memory.base import MemoryRecord

    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=0)
    (root / "aef.yaml").write_text(COMMAND_PROVIDER_CONFIG, encoding="utf-8")
    (site,) = run_migrate(root, agent_root=".claude/agents").prompt_agents

    # Two distinct runs under one signature: ADR 0110's threshold for a lesson.
    memory_path = root / "memory.jsonl"
    store = FileMemoryStore(path=memory_path)
    for i in range(2):
        store.write(
            MemoryRecord(
                kind="failure",
                content={
                    "verbal_feedback": "ALWAYS-CITE-THE-PERMIT-ID",
                    "failing_nodes": ["prompt_agent"],
                    "objective": "an earlier question",
                },
                run_id=f"planted-{i}",
                agent_id="a1",
                created_at=datetime(2026, 9, 4, 12, i, tzinfo=UTC),
            )
        )

    monkeypatch.chdir(root)
    state = run_graph_module(
        site.out_relative,
        agent_id="a1",
        objective="what are the preconditions?",
        config_path=root / "aef.yaml",
        memory_path=memory_path,
    )

    # This config declares no `{system}` slot, so `CommandProvider`
    # concatenates: persona, then the user turn. Which makes the ordering
    # inside the user turn readable here — objective first, lessons after.
    echoed = str(state.working_memory["prompt_agent"])
    assert "ALWAYS-CITE-THE-PERMIT-ID" in echoed, echoed
    assert echoed.index("what are the preconditions?") < echoed.index("ALWAYS-CITE")
    assert state.retrieved_context, "the retrieve node wrote nothing"
    # And that slotless provider did NOT cost the run its score (R3).
    assert state.errors == []

    # And the outcome signal ADR 0118 records now has something to record.
    written = [
        r
        for r in FileMemoryStore(path=memory_path).query("success", agent_id="a1", limit=20)
        if not r.run_id.startswith("planted-")
    ]
    assert written, "reflection wrote no record for this run"
    assert written[0].content["retrieved_signatures"] == ["failure:prompt_agent"]


# The count migrate prints is the adopter's, not aef's own (ADR 0176, F1)
# ---------------------------------------------------------------------------


def test_migrate_does_not_count_the_skill_adopt_wrote(tmp_path: Path) -> None:
    """THE regression test for H1's finding 1, reproduced on the pilot clone:

        $ aef adopt --dir clone
        adopt   skills=5
        migrate skills=6      <- the sixth is adopt's own new-model-check

    `discover_skills` globbed `<skills>/*/SKILL.md` with no exclusion, so the
    scaffold counted its own output as the adopter's prompt surface — a number
    that changes the moment adoption runs, which is the same class of defect
    ADR 0172 D4 fixed on adopt's side.
    """
    from aef.harness.zones import ADOPT_SKILL_PATH

    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=2)
    ours = root / ADOPT_SKILL_PATH
    ours.parent.mkdir(parents=True)
    ours.write_text("---\nname: new-model-check\n---\n\nRe-audit.\n", encoding="utf-8")

    assert len(discover_skills(root)) == 3, "the raw listing still sees all three"
    assert len(discover_adopter_skills(root)) == 2, "the adopter has two"
    assert ADOPT_SKILL_PATH not in discover_adopter_skills(root)


def test_the_report_counts_two_and_still_names_the_third_marked(tmp_path: Path) -> None:
    """Excluding it from the LISTING as well would make `aef migrate` silent
    about a file it declined to migrate, which is the one thing that block
    exists not to be.

    The header used to read `found 2 skill(s) and did NOT migrate any of them:`
    over THREE rows, and this test pinned it (F-M8-2, ADR 0187 / 0189). ADR
    0172's D4 reason for the two — a subtotal that does not change the moment
    adoption runs — survives as the parenthetical; what does not survive is a
    leading number that was not the number of rows beneath it."""
    from aef.harness.zones import ADOPT_SKILL_PATH

    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=2)
    ours = root / ADOPT_SKILL_PATH
    ours.parent.mkdir(parents=True)
    ours.write_text("---\nname: new-model-check\n---\n\nRe-audit.\n", encoding="utf-8")

    text = report(run_migrate(root, write=False))

    assert "found 3 skill(s) and did NOT migrate any of them (2 yours + 1 aef's own):" in text, text
    assert text.count("  SKILL    ") == 3, "the header counts the rows it heads"
    assert f"SKILL    {ADOPT_SKILL_PATH}   (aef's own — not yours)" in text, text
    assert text.count("  SKILL    ") == 3, "all three are still named"


def test_the_skill_header_counts_its_rows_with_no_aef_skill_present(tmp_path: Path) -> None:
    """The other shape of ADR 0189's fix: with aef's own skill absent there is
    no split to report, so the header is the bare count — and it still equals
    the number of rows beneath it, which is the property that broke (F-M8-2)."""
    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=3)

    text = report(run_migrate(root, write=False))

    header = next(ln for ln in text.splitlines() if "skill(s) and did NOT migrate" in ln)
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("SKILL ")]
    assert header.strip() == "found 3 skill(s) and did NOT migrate any of them:", header
    assert int(header.strip().split()[1]) == len(rows) == 3
    assert "aef's own" not in header, header


def test_adopt_and_migrate_agree_on_the_same_tree(tmp_path: Path) -> None:
    """The join, run for real: the REAL `aef adopt` into the REAL migrate
    discovery. Two numbers nobody compares is how this repo keeps finding
    drift (ADR 0091), so they are compared."""
    from aef.cli.adopt import detect_prompt_surface, run_adopt

    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=3)
    run_adopt(root)

    assert detect_prompt_surface(root).skills == len(discover_adopter_skills(root)) == 3


def test_a_repo_with_no_adopt_skill_is_unchanged(tmp_path: Path) -> None:
    """The control: the exclusion must not remove anything on a tree adopt has
    never touched."""
    root = _prompt_repo(tmp_path, names=("pilot-accela",), skills=4)

    assert discover_adopter_skills(root) == discover_skills(root)
    assert len(discover_adopter_skills(root)) == 4


def test_the_report_wiring_string_is_the_rendered_modules_node_order(tmp_path: Path) -> None:
    """ADR 0183 found the report printing a three-node wiring while the module
    it wrote in the same run had four. One constant now; this reads the
    module back and asserts its `add_node` order is what the report says."""
    import re

    from aef.cli.migrate import PROMPT_AGENT_WIRING, run_migrate

    root = _prompt_repo(tmp_path, names=("wiring-probe",), skills=0)
    result = run_migrate(root)
    (site,) = result.prompt_agents
    source = (root / site.out_relative).read_text(encoding="utf-8")
    # The rendered module declares the order as an entry node plus a chain of
    # edges; walk it.
    entry = re.search(r'entry_node="([a-z_]+)"', source)
    assert entry is not None, source[:400]
    edges = dict(re.findall(r'Edge\(from_node="([a-z_]+)", to_node="([a-z_]+)"\)', source))
    walked, node = [], entry.group(1)
    while node in edges and node not in walked:
        walked.append(node)
        node = edges[node]
    walked.append(node)
    expected = [n.strip() for n in PROMPT_AGENT_WIRING.replace("END", "").split("->") if n.strip()]
    assert walked == expected, (walked, expected)
    from aef.cli.migrate import report

    rendered = report(result)
    text = rendered if isinstance(rendered, str) else "\n".join(rendered)
    assert PROMPT_AGENT_WIRING in text


def test_mixed_native_personas_report_each_actual_zone(tmp_path: Path) -> None:
    for rel in (".claude/agents/source.md", ".grok/agents/checker.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Read supplied evidence.\n")
    result = run_migrate(tmp_path, agent_root=".claude/agents")
    text = report(result)
    assert ".claude/agents/source.md is Zone A" in text
    assert ".grok/agents/checker.md is Zone C" in text
    assert "Only some persona files are inside Zone A" in text
    assert "The PERSONA FILES are inside it too" not in text
