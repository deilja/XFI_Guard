import json

from xfi_guard.monitor import write_snapshot


def test_write_snapshot(tmp_path):
    target = tmp_path / "logs" / "monitor.jsonl"
    write_snapshot(str(target), [{"name": "disk", "status": "ok"}])
    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["results"][0]["name"] == "disk"
    assert "timestamp" in record
