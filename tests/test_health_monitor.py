from xfi_guard.discovery import NodeSnapshot, ServiceState
from xfi_guard.health_monitor import HealthMonitor, IncidentLevel


def snapshot(*, awg=True, internet=True, xray=ServiceState.RUNNING):
    return NodeSnapshot(
        node_id="entry-01",
        role="ENTRY",
        services={"xray": xray, "awg": ServiceState.RUNNING},
        awg_handshake=awg,
        internet_reachable=internet,
    )


def test_first_snapshot_creates_no_incident():
    assert HealthMonitor().update(snapshot()) == []


def test_awg_loss_creates_high_incident():
    monitor = HealthMonitor()
    monitor.update(snapshot())
    incidents = monitor.update(snapshot(awg=False))
    assert len(incidents) == 1
    assert incidents[0].level is IncidentLevel.HIGH
    assert "AWG" in incidents[0].title


def test_service_stop_creates_incident():
    monitor = HealthMonitor()
    monitor.update(snapshot())
    incidents = monitor.update(snapshot(xray=ServiceState.STOPPED))
    assert len(incidents) == 1
    assert incidents[0].node_id == "entry-01"
