"""Skill proposals (ADR 0117): WikiSkill's third layer, minus the part that
rewrites the agent at runtime. Every test here is a refusal or a provenance
check — what the module will not do matters more than the markdown."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.skills import (
    HARNESS_DIRS,
    SkillProposalError,
    propose_skills,
    render_skill,
    slug_for,
)
from aef.services.knowledge.base import KnowledgeEntry
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore

T = datetime(2026, 9, 3, tzinfo=UTC)


def _entry(sig: str = "failure:fetch>parse", n: int = 3, agent: str = "a1") -> KnowledgeEntry:
    return KnowledgeEntry(
        signature=sig,
        kind="failure",
        content={
            "signature": sig,
            "latest_feedback": "1 error(s) recorded; fetch timed out",
            "objective": "settle the invoice",
            "run_ids": [f"r{i}" for i in range(n)],
            "failing_nodes": ["fetch", "parse"],
        },
        agent_id=agent,
        source_record_ids=tuple(f"rec{i}" for i in range(n)),
        first_seen=T,
        last_seen=T,
        runs_since_last_seen=7,
    )


def _store(*entries: KnowledgeEntry) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for e in entries:
        store.upsert(e)
    return store


def test_render_carries_every_provenance_field_from_the_entry() -> None:
    text = render_skill(_entry())
    assert text.startswith("---\nname: failure-fetch-parse\n")
    assert "PROPOSED, not adopted" in text
    assert "occurrences (distinct runs): 3" in text
    assert "runs since last seen: 7" in text
    assert "run ids: r0, r1, r2" in text
    assert "source record ids: rec0, rec1, rec2" in text
    assert "fetch timed out" in text
    assert "Nothing loads this file until a person moves it" in text


def test_slug_is_stable_and_filesystem_safe() -> None:
    assert slug_for(_entry("failure:fetch>parse")) == "failure-fetch-parse"
    assert slug_for(_entry("failure:Weird Node/Name!")) == "failure-weird-node-name"


def test_proposes_one_draft_per_well_evidenced_entry(tmp_path: Path) -> None:
    store = _store(_entry("failure:fetch", n=3), _entry("failure:auth", n=2))
    proposals = propose_skills(store, tmp_path / "proposals", agent_id="a1", min_occurrences=3)
    assert [p.slug for p in proposals] == ["failure-fetch"]
    assert proposals[0].written
    assert (tmp_path / "proposals" / "failure-fetch" / "SKILL.md").read_text().startswith("---")


def test_never_overwrites_an_existing_draft(tmp_path: Path) -> None:
    store = _store(_entry("failure:fetch"))
    target = tmp_path / "proposals" / "failure-fetch" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# edited by a person\n")
    proposals = propose_skills(store, tmp_path / "proposals", agent_id="a1")
    assert proposals[0].written is False
    assert target.read_text() == "# edited by a person\n"


@pytest.mark.parametrize("harness_dir", HARNESS_DIRS)
def test_refuses_to_write_where_a_harness_loads_from(tmp_path: Path, harness_dir: str) -> None:
    store = _store(_entry())
    with pytest.raises(SkillProposalError, match="runtime self-modification"):
        propose_skills(store, tmp_path / harness_dir / "skills", agent_id="a1")
    assert not (tmp_path / harness_dir).exists()


def test_is_agent_scoped(tmp_path: Path) -> None:
    store = _store(_entry("failure:fetch", agent="a1"), _entry("failure:auth", agent="a2"))
    proposals = propose_skills(store, tmp_path / "p", agent_id="a1")
    assert [p.slug for p in proposals] == ["failure-fetch"]


def test_the_module_touches_neither_evolution_nor_a_model() -> None:
    """Constraint #7 by structure: the proposal path imports nothing from
    aef.evolution and nothing that calls a model."""
    source = Path("aef/harness/skills.py").read_text()
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.startswith("aef.evolution") for name in imported), imported
    assert not any(name.startswith("aef.providers") for name in imported), imported
    assert not any(name.startswith("aef.reasoning") for name in imported), imported


def test_cli_drafts_from_a_durable_memory_store(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from aef.cli.main import main
    from aef.harness.memory_store import FileMemoryStore
    from aef.services.memory.base import MemoryRecord

    memory = FileMemoryStore(path=tmp_path / "memory.jsonl")
    for i in range(3):
        memory.write(
            MemoryRecord(
                kind="failure",
                content={"failing_nodes": ["fetch"], "verbal_feedback": "fetch timed out"},
                run_id=f"r{i}",
                agent_id="a1",
                created_at=T,
            )
        )
    out = tmp_path / "proposals"
    code = main(
        [
            "loop",
            "skills",
            "--memory",
            str(tmp_path / "memory.jsonl"),
            "--agent-id",
            "a1",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert (out / "failure-fetch" / "SKILL.md").exists()
    assert "1 proposal(s) written" in capsys.readouterr().out
    # And the refusal reaches the CLI as a non-zero exit, not a traceback.
    code = main(
        [
            "loop",
            "skills",
            "--memory",
            str(tmp_path / "memory.jsonl"),
            "--agent-id",
            "a1",
            "--out",
            str(tmp_path / ".claude" / "skills"),
        ]
    )
    assert code != 0
