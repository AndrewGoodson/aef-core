"""`Graph` — a versioned, validated, diffable, visualizable collection of
`Node`/`Edge`. Topology is static and declared up front (report §4); the
handful of dynamic-routing decisions a node makes at runtime are checked
against this declared topology by `GraphExecutor`, never trusted blindly.

Mandatory subgraph API per blueprint Part 14: `compile()`, `validate()`,
`diff(other)`, `visualize()`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from aef.kernel.contracts import Edge, Node


class GraphValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Graph:
    id: str
    version: str  # semver, independent per subgraph (blueprint §2.4)
    nodes: Mapping[str, Node]
    edges: Sequence[Edge]
    entry_node: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes)))
        object.__setattr__(self, "edges", tuple(self.edges))

    def validate(self) -> None:
        errors: list[str] = []
        if self.entry_node not in self.nodes:
            errors.append(f"entry_node {self.entry_node!r} is not a declared node")
        for edge in self.edges:
            if edge.from_node not in self.nodes:
                errors.append(f"edge.from_node {edge.from_node!r} is not a declared node")
            for target in edge.targets:
                if target not in self.nodes:
                    errors.append(f"edge from {edge.from_node!r} routes to unknown node {target!r}")
        for node in self.nodes.values():
            if node.fallback_node_id is not None and node.fallback_node_id not in self.nodes:
                errors.append(
                    f"node {node.id!r} fallback_node_id {node.fallback_node_id!r} "
                    f"is not a declared node"
                )
        if errors:
            raise GraphValidationError("; ".join(errors))

    def edges_from(self, node_id: str) -> list[Edge]:
        """Declared outgoing edges for `node_id`, highest priority first —
        the deterministic tie-break blueprint §2.2 requires."""
        return sorted((e for e in self.edges if e.from_node == node_id), key=lambda e: -e.priority)

    def compile(self) -> CompiledGraph:
        self.validate()
        return CompiledGraph(graph=self)

    def diff(self, other: Graph) -> GraphDiff:
        self_ids, other_ids = set(self.nodes), set(other.nodes)
        nodes_added = frozenset(other_ids - self_ids)
        nodes_removed = frozenset(self_ids - other_ids)
        nodes_changed = frozenset(
            nid
            for nid in (self_ids & other_ids)
            if self.nodes[nid].version != other.nodes[nid].version
        )
        self_edges, other_edges = set(self.edges), set(other.edges)
        return GraphDiff(
            nodes_added=nodes_added,
            nodes_removed=nodes_removed,
            nodes_changed=nodes_changed,
            edges_added=tuple(other_edges - self_edges),
            edges_removed=tuple(self_edges - other_edges),
        )

    def visualize(self) -> str:
        """Mermaid flowchart source — pasted straight into docs/PRs."""
        lines = ["flowchart TD"]
        for node_id in self.nodes:
            marker = " (entry)" if node_id == self.entry_node else ""
            lines.append(f'  {node_id}["{node_id}{marker}"]')
        for edge in self.edges:
            label = f"|p{edge.priority}|" if edge.priority else ""
            for target in edge.targets:
                lines.append(f"  {edge.from_node} -->{label} {target}")
        return "\n".join(lines)


@dataclass(frozen=True)
class CompiledGraph:
    graph: Graph


@dataclass(frozen=True)
class GraphDiff:
    nodes_added: frozenset[str] = field(default_factory=frozenset)
    nodes_removed: frozenset[str] = field(default_factory=frozenset)
    nodes_changed: frozenset[str] = field(default_factory=frozenset)
    edges_added: tuple[Edge, ...] = ()
    edges_removed: tuple[Edge, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.nodes_added
            or self.nodes_removed
            or self.nodes_changed
            or self.edges_added
            or self.edges_removed
        )
