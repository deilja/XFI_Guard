"""Корреляция инцидентов с учётом графа зависимостей.

Слой только анализирует данные. Исполнение исправлений здесь запрещено.
"""
from __future__ import annotations

from dataclasses import dataclass
from .health_monitor import HealthIncident, IncidentLevel
from .topology import DependencyGraph, NodeState


@dataclass(frozen=True)
class CorrelatedIncident:
    root_node_id: str
    level: IncidentLevel
    title: str
    details: str
    affected_nodes: tuple[str, ...]
    source_incidents: tuple[HealthIncident, ...]


class IncidentCorrelator:
    def correlate(
        self, graph: DependencyGraph, incidents: list[HealthIncident]
    ) -> list[CorrelatedIncident]:
        if not incidents:
            return []

        by_node = {incident.node_id: incident for incident in incidents}
        roots = graph.root_causes()
        if not roots:
            roots = sorted(by_node)

        result: list[CorrelatedIncident] = []
        for root in roots:
            related = self._reachable_dependents(graph, root) & set(by_node)
            if root in by_node:
                related.add(root)
            if not related:
                continue
            ordered = tuple(sorted(related))
            source = tuple(by_node[node] for node in ordered)
            level = max(source, key=self._severity).level
            affected = tuple(sorted(self._reachable_dependents(graph, root) & set(graph.nodes)))
            title = f"Корневая неисправность: {root}"
            details = (
                f"Обнаружено {len(source)} связанных событий. "
                f"Первичной точкой отказа определён узел {root}."
            )
            result.append(CorrelatedIncident(root, level, title, details, affected, source))
        return result

    @staticmethod
    def _severity(incident: HealthIncident) -> int:
        return {
            IncidentLevel.INFO: 0,
            IncidentLevel.WARNING: 1,
            IncidentLevel.HIGH: 2,
            IncidentLevel.CRITICAL: 3,
        }[incident.level]

    @staticmethod
    def _reachable_dependents(graph: DependencyGraph, node_id: str) -> set[str]:
        result: set[str] = set()
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            for dependent in graph.dependents_of(current):
                if dependent not in result:
                    result.add(dependent)
                    queue.append(dependent)
        return result
