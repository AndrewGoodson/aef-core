"""The audit trail has to survive the process.

`InMemoryAuditLogWriter` was the only implementation shipped, so every entry
died with the interpreter that wrote it — while `roadmap.md` listed
`AuditLogWriter` under Phase 1 DONE. The interface was done. An audit trail
you cannot read after the fact is not one, and after-the-fact is the only
time anybody reads one (ADR 0083).

`grep -rln FileMemoryStore tests/` returned zero files once before, for the
durable store the whole loop depends on. This file exists so the same is not
true of the durable audit log.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from aef.security.tool import (
    FileAuditLogWriter,
    InMemoryAuditLogWriter,
    PolicyEngine,
    Tool,
    ToolCall,
)


@dataclass(frozen=True)
class _Tool(Tool):
    name: str
    required_scopes: tuple[str, ...] = ()

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {}


SECRET = "sk-live-DO-NOT-LOG-THIS"


def _call() -> ToolCall:
    return ToolCall(
        tool_name="fetch",
        arguments={"url": "https://example.test", "api_key": SECRET},
        risk=0.2,
    )


def test_every_evaluation_reaches_the_file(tmp_path: Path) -> None:
    writer = FileAuditLogWriter(tmp_path / "audit.jsonl")
    engine = PolicyEngine(audit_log=writer)
    engine.evaluate(_Tool(name="fetch", required_scopes=("net.read",)), _call())
    engine.evaluate(_Tool(name="fetch", required_scopes=("net.read",)), _call())

    entries = writer.read()
    assert len(entries) == 2
    assert entries[0]["tool"] == "fetch"
    assert entries[0]["decision"] == "deny", "deny-by-default, and the reason is recorded"
    assert entries[0]["reason"]


def test_it_survives_a_new_writer_over_the_same_file(tmp_path: Path) -> None:
    """The whole point: a later process can read what an earlier one wrote."""
    path = tmp_path / "audit.jsonl"
    PolicyEngine(audit_log=FileAuditLogWriter(path)).evaluate(_Tool(name="fetch"), _call())
    assert len(FileAuditLogWriter(path).read()) == 1


def test_argument_values_are_redacted_and_names_are_not(tmp_path: Path) -> None:
    """A tool call's arguments are where an API key lives, and an audit log is
    exactly the file that gets shipped to an aggregator or attached to a
    ticket. The names make the entry useful; the values make it dangerous."""
    path = tmp_path / "audit.jsonl"
    PolicyEngine(audit_log=FileAuditLogWriter(path)).evaluate(_Tool(name="fetch"), _call())

    raw = path.read_text()
    assert SECRET not in raw, "a secret reached the audit log"
    assert "api_key" in raw, "the argument names must survive or the entry says nothing"
    assert FileAuditLogWriter(path).read()[0]["call"]["arguments"]["api_key"] == "<redacted>"


def test_redaction_can_be_turned_off_deliberately(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    writer = FileAuditLogWriter(path, redact_arguments=False)
    PolicyEngine(audit_log=writer).evaluate(_Tool(name="fetch"), _call())
    assert writer.read()[0]["call"]["arguments"]["api_key"] == SECRET


def test_an_unserialisable_argument_does_not_lose_the_entry(tmp_path: Path) -> None:
    """Losing the whole record because one argument would not serialise is
    the silent-drop failure this module's own comments warn about."""
    path = tmp_path / "audit.jsonl"
    writer = FileAuditLogWriter(path, redact_arguments=False)
    PolicyEngine(audit_log=writer).evaluate(
        _Tool(name="fetch"),
        ToolCall(tool_name="fetch", arguments={"conn": object()}, risk=0.0),
    )
    assert len(writer.read()) == 1


def test_a_damaged_log_raises_rather_than_skipping(tmp_path: Path) -> None:
    """An audit log that silently drops records is worse than one that admits
    it is damaged."""
    path = tmp_path / "audit.jsonl"
    PolicyEngine(audit_log=FileAuditLogWriter(path)).evaluate(_Tool(name="fetch"), _call())
    path.write_text(path.read_text() + "{not json\n")
    with pytest.raises(ValueError, match="malformed audit entry"):
        FileAuditLogWriter(path).read()


def test_a_missing_log_reads_empty_rather_than_raising(tmp_path: Path) -> None:
    assert FileAuditLogWriter(tmp_path / "never-written.jsonl").read() == []


def test_the_default_writer_is_reachable() -> None:
    """Constructed without an explicit writer, the default landed on a private
    attribute with no accessor — entries were written and unreachable."""
    engine = PolicyEngine()
    assert isinstance(engine.audit_log, InMemoryAuditLogWriter)
    engine.evaluate(_Tool(name="fetch"), _call())
    assert len(engine.audit_log.entries) == 1  # type: ignore[union-attr]


def test_the_cli_can_wire_a_durable_log() -> None:
    from aef.cli.main import build_parser

    args = build_parser().parse_args(["run", "m", "--objective", "o", "--audit-log", "audit.jsonl"])
    assert args.audit_log == "audit.jsonl"


def test_the_roadmap_claim_matches_what_ships() -> None:
    """It listed AuditLogWriter under Phase 1 DONE while shipping no durable
    writer. Either the roadmap becomes true or it becomes honest; this is the
    assertion that keeps whichever was chosen from drifting back."""
    roadmap = (Path(__file__).resolve().parents[2] / "docs" / "roadmap.md").read_text()
    assert "FileAuditLogWriter" in roadmap
