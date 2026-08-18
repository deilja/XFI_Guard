from xfi_guard.topology import DependencyGraph, NodeState, TopologyNode, build_cluster


def test_dependency_graph_and_root_cause():
    graph = build_cluster(
        [
            TopologyNode("entry-01", "ENTRY", NodeState.HEALTHY),
            TopologyNode("entry-02", "ENTRY", NodeState.DOWN),
            TopologyNode("exit-01", "EXIT", NodeState.DOWN),
            TopologyNode("master", "MASTER", NodeState.HEALTHY),
        ],
        [
            ("master", "entry-01", "управление"),
            ("master", "entry-02", "управление"),
            ("entry-01", "exit-01", "выход в Интернет"),
            ("entry-02", "exit-01", "выход в Интернет"),
        ],
    )

    assert graph.dependencies_of("entry-02") == ["exit-01"]
    assert graph.dependents_of("exit-01") == ["entry-01", "entry-02"]
    assert graph.root_causes() == ["exit-01"]


def test_unknown_nodes_are_not_accepted_in_links():
    graph = DependencyGraph()
    graph.add_node(TopologyNode("master", "MASTER"))
    try:
        graph.add_dependency("master", "missing")
    except KeyError:
        pass
    else:
        raise AssertionError("ожидалась ошибка для неизвестного узла")
