"""Real, dependency-free `MemoryStore` backend — the Phase 0/1 default and
what `examples/` runs against."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime

from aef.services.memory.base import MemoryKind, MemoryRecord, MemoryStore


class InMemoryMemoryStore(MemoryStore):
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._clock = clock or (lambda: datetime.now(UTC))

    def write(self, record: MemoryRecord) -> str:
        if record.created_at is None:
            record = dataclasses.replace(record, created_at=self._clock())
        self._records[record.id] = record
        return record.id

    def query(
        self,
        kind: MemoryKind,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        tags: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[MemoryRecord]:
        wanted_tags = set(tags)
        matches = [
            r
            for r in self._records.values()
            if r.kind == kind
            and (run_id is None or r.run_id == run_id)
            and (agent_id is None or r.agent_id == agent_id)
            and wanted_tags.issubset(r.tags)
        ]
        matches.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return matches[:limit]

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)
