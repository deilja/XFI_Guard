from xfi_guard.discovery import DiscoveryPolicy, NodeSnapshot, ServiceState


def test_health_score_requires_positive_telemetry():
    snapshot = NodeSnapshot(
        node_id="entry-01",
        role="ENTRY",
        services={"xray": ServiceState.RUNNING, "awg": ServiceState.RUNNING},
        awg_handshake=True,
        internet_reachable=True,
    )
    assert snapshot.health_score() == 100


def test_stopped_service_reduces_score():
    snapshot = NodeSnapshot(
        node_id="entry-01",
        role="ENTRY",
        services={"xray": ServiceState.STOPPED, "awg": ServiceState.RUNNING},
        awg_handshake=True,
        internet_reachable=True,
    )
    assert snapshot.health_score() == 75


def test_discovery_drops_unapproved_fields():
    payload = {"node_id": "entry-01", "role": "ENTRY", "password": "secret"}
    clean = DiscoveryPolicy.sanitize(payload)
    assert clean == {"node_id": "entry-01", "role": "ENTRY"}
