"""Topology discovery and dependency graph for XFI Guard.

Pure data/model layer: no network calls and no command execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeState(str, Enum):
    UNKNOWN = "неизвестно"
    HEALTHY = "в норме"
    DEGRADED = "есть проблемы"
    DOWN = "не работает"


@dataclass(frozen=True)
class TopologyNode:
    node_id: str
    role: str
    state: NodeState = NodeState.UNKNOWN
    address: str | None = None


@dataclass(frozen=True)
class Dependency:
    source: str
    target: str
    kind: str = "управление"


@dataclass
class DependencyGraph:
    nodes: dict[str, TopologyNode] = field(default_factory=dict)
    dependencies: set[Dependency] = field(default_factory=set)

    def add_node(self, node: TopologyNode) -> None:
        self.nodes[node.node_id] = node

    def add_dependency(self, source: str, target: str, kind: str = "управление") -> None:
        if source not in self.nodes or target not in self.nodes:
            raise KeyError("зависимость ссылается на неизвестный узел")
        self.dependencies.add(Dependency(source, target, kind))

    def dependents_of(self, node_id: str) -> list[str]:
        return sorted(d.source for d in self.dependencies if d.target == node_id)

    def dependencies_of(self, node_id: str) -> list[str]:
        return sorted(d.target for d in self.dependencies if d.source == node_id)

    def root_causes(self) -> list[str]:
        """Return failed nodes that have no failed dependency below them."""
        failed = {n.node_id for n in self.nodes.values() if n.state is NodeState.DOWN}
        roots = []
        for node_id in failed:
            failed_dependencies = set(self.dependencies_of(node_id)) & failed
            if not failed_dependencies:
                roots.append(node_id)
        return sorted(roots)


def build_cluster(nodes: list[TopologyNode], links: list[tuple[str, str, str]]) -> DependencyGraph:
    graph = DependencyGraph()
    for node in nodes:
        graph.add_node(node)
    for source, target, kind in links:
        graph.add_dependency(source, target, kind)
    return graph
