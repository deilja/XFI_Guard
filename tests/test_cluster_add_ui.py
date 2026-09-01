from xfi_guard import cluster_add_ui, cluster_ui


def test_add_vps_requires_cluster_credentials(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_TOKEN", raising=False)
    monkeypatch.delenv("XFI_GUARD_CLUSTER_SECRET", raising=False)
    assert cluster_add_ui._credentials_ready() is False


def test_add_vps_credentials_ready(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_CLUSTER_TOKEN", "test-token")
    monkeypatch.setenv("XFI_GUARD_CLUSTER_SECRET", "test-secret")
    assert cluster_add_ui._credentials_ready() is True


def test_add_vps_requires_master_url(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_CLUSTER_MASTER_URL", raising=False)
    assert cluster_add_ui._master_url() == ""


def test_bare_master_hostname_is_normalized_to_https():
    assert cluster_add_ui._normalize_master_input("Ger.deilja.online") == "https://Ger.deilja.online"


def test_full_master_url_is_normalized():
    assert cluster_add_ui._normalize_master_input("https://ger.deilja.online/") == "https://ger.deilja.online"


def test_add_vps_rejects_plain_http_remote_master():
    try:
        cluster_ui._validate_master_url("http://10.0.0.10:8765")
    except RuntimeError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("remote HTTP Master URL must be rejected")


def test_cluster_menu_contains_add_vps():
    keyboard = cluster_ui._buttons().inline_keyboard
    callbacks = [button.callback_data for row in keyboard for button in row]
    assert "cluster:add" in callbacks
