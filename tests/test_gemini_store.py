from xfi_guard.gemini_store import DEFAULT_MODEL, load, save


def test_gemini_store_roundtrip(tmp_path):
    path = tmp_path / "gemini.json"
    save("AIza-test-key", "gemini-2.5-pro", path)
    data = load(path)
    assert data["api_key"] == "AIza-test-key"
    assert data["model"] == "gemini-2.5-pro"
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_default_model(tmp_path):
    assert load(tmp_path / "missing.json")["model"] == DEFAULT_MODEL
