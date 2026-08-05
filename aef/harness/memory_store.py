"""A durable `MemoryStore` for the loop.

`InMemoryMemoryStore` is real and fully tested, and it is discarded when the
process exits. That is fine for a single graph run and fatal for a loop whose
whole premise is learning across runs: `aef loop cycle` constructed one
inline, so the evidence the proposer reads was empty on every invocation and
the reflection wire (ADR 0065) could never fire from the CLI (ADR 0069).

JSONL, append-only, one record per line. Deliberately not a database: the
loop writes a handful of records per run, the file is readable by a human
investigating a halt, and a dependency would have to earn its place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aef.services.memory.base import MemoryKind, MemoryRecord, MemoryStore


@dataclass(frozen=True)
class FileMemoryStore(MemoryStore):
    """Records persist across processes, which is what makes the loop learn."""

    path: Path

    def _load(self) -> list[MemoryRecord]:
        if not self.path.is_file():
            return []
        out: list[MemoryRecord] = []
        for number, line in enumerate(self.path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                out.append(
                    MemoryRecord(
                        kind=payload["kind"],
                        content=payload["content"],
                        run_id=payload.get("run_id"),
                        agent_id=payload.get("agent_id"),
                        tags=tuple(payload.get("tags", ())),
                        id=payload["id"],
                        created_at=(
                            datetime.fromisoformat(payload["created_at"])
                            if payload.get("created_at")
                            else None
                        ),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                # Loud, not skipped: a memory file that silently drops records
                # gives the proposer less evidence than it thinks it has.
                raise ValueError(f"{self.path}:{number}: malformed memory record: {exc}") from exc
        return out

    def write(self, record: MemoryRecord) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "kind": record.kind,
            "content": record.content,
            "run_id": record.run_id,
            "agent_id": record.agent_id,
            "tags": list(record.tags),
            "id": record.id,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return record.id

    def get(self, record_id: str) -> MemoryRecord | None:
        return next((r for r in self._load() if r.id == record_id), None)

    def query(
        self,
        kind: MemoryKind,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        tags: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[MemoryRecord]:
        matches = [
            r
            for r in self._load()
            if r.kind == kind
            and (run_id is None or r.run_id == run_id)
            and (agent_id is None or r.agent_id == agent_id)
            and all(t in r.tags for t in tags)
        ]
        return list(reversed(matches))[:limit]  # most-recent-first
