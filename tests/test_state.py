from xfi_guard.state import StateStore


def test_state_persists(tmp_path):
    path = tmp_path / "state.json"
    state = StateStore(path)
    assert not state.seen("abc")
    state.mark_seen("abc", "now")
    state.save()

    restored = StateStore(path)
    assert restored.seen("abc")
