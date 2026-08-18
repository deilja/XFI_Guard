from xfi_guard.health_monitor import HealthIncident, IncidentLevel
from xfi_guard.incident_correlator import IncidentCorrelator
from xfi_guard.topology import DependencyGraph, NodeState, TopologyNode


def incident(node_id, title):
    from datetime import datetime, timezone
    return HealthIncident(node_id, IncidentLevel.HIGH, title, "тест", datetime.now(timezone.utc))


def test_exit_is_root_for_dependent_entries():
    graph = DependencyGraph()
    graph.add_node(TopologyNode("exit-01", "EXIT", NodeState.DOWN))
    graph.add_node(TopologyNode("entry-01", "ENTRY", NodeState.DOWN))
    graph.add_node(TopologyNode("entry-03", "ENTRY", NodeState.DOWN))
    graph.add_dependency("entry-01", "exit-01", "выход")
    graph.add_dependency("entry-03", "exit-01", "выход")

    result = IncidentCorrelator().correlate(
        graph,
        [incident("exit-01", "AWG недоступен"), incident("entry-01", "Нет выхода"), incident("entry-03", "Нет выхода")],
    )
    assert len(result) == 1
    assert result[0].root_node_id == "exit-01"
    assert result[0].affected_nodes == ("entry-01", "entry-03")
    assert len(result[0].source_incidents) == 3
