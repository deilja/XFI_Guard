from xfi_guard.cluster_status import cluster_summary, node_status


def test_node_status_online_degraded_offline():
    now = 1000.0
    assert node_status({"last_seen": 950}, now)[0] == "online"
    assert node_status({"last_seen": 850}, now)[0] == "degraded"
    assert node_status({"last_seen": 700}, now)[0] == "offline"


def test_cluster_summary():
    result = cluster_summary([
        {"name": "a", "last_seen": 950},
        {"name": "b", "last_seen": 850},
        {"name": "c", "last_seen": 700},
    ], 1000.0)
    assert result["status"] == "degraded"
    assert result["counts"] == {"online": 1, "degraded": 1, "offline": 1}
