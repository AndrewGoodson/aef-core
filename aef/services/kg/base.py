"""`GraphStore` — Phase 2 interface stub (report §14 / blueprint Part 6).

No implementation ships in Phase 0/1: knowledge-graph memory (semantic +
procedural, temporal-fact validity) is out of scope until Phase 2. This
module exists now so `kernel.Services` has a stable slot to inject into,
and so a future adapter (Neo4j, FalkorDB, or Apache AGE — see docs/adr/0003
for why none is chosen yet) only has to implement this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str
    properties: dict[str, Any]
    valid_from: datetime | None = None
    valid_until: datetime | None = None


@dataclass(frozen=True)
class Relation:
    source_id: str
    target_id: str
    kind: str
    properties: dict[str, Any]
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class GraphStore(ABC):
    """Temporal entity/relationship store. See report §14 for the rationale
    (flat vector memory cannot express "true then, false now")."""

    @abstractmethod
    def upsert_entity(self, entity: Entity) -> None:
        raise NotImplementedError("GraphStore is a Phase 2 interface; no backend is wired yet")

    @abstractmethod
    def upsert_relation(self, relation: Relation) -> None:
        raise NotImplementedError("GraphStore is a Phase 2 interface; no backend is wired yet")

    @abstractmethod
    def query_entities(self, kind: str, *, as_of: datetime | None = None) -> list[Entity]:
        raise NotImplementedError("GraphStore is a Phase 2 interface; no backend is wired yet")

    @abstractmethod
    def query_neighbors(self, entity_id: str, *, as_of: datetime | None = None) -> list[Relation]:
        raise NotImplementedError("GraphStore is a Phase 2 interface; no backend is wired yet")
