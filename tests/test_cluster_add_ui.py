from pathlib import Path

from xfi_guard import cluster_add_ui, cluster_ui, node_bootstrap, password_bootstrap


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


def test_ssh_auth_failure_is_detected():
    assert cluster_add_ui._is_ssh_auth_failure("root@10.0.0.1: Permission denied (publickey,password).")
    assert cluster_add_ui._is_ssh_auth_failure("Permission denied (publickey)")
    assert not cluster_add_ui._is_ssh_auth_failure("Connection timed out")


def test_safe_output_redacts_cluster_credentials():
    output = "token=test-token secret=test-secret"
    assert cluster_add_ui._safe_output(output, "test-token", "test-secret") == "token=<TOKEN> secret=<SECRET>"


def test_add_vps_uses_xfi_guard_identity(monkeypatch):
    captured = {}

    def fake_bootstrap(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return True, "XFI_GUARD_PROVISION_OK"

    assert str(cluster_add_ui.DEFAULT_IDENTITY_FILE).endswith("/.ssh/xfi_guard_cluster_ed25519")
    assert cluster_add_ui.DEFAULT_IDENTITY_FILE == node_bootstrap.Path(
        node_bootstrap.os.path.expanduser("~/.ssh/xfi_guard_cluster_ed25519")
    )

    # The actual callback passes this identity explicitly; keep this regression
    # test focused on the single source of truth used by the UI.
    monkeypatch.setattr(cluster_add_ui, "bootstrap", fake_bootstrap)
    assert captured == {}


def test_password_bootstrap_passes_cluster_credentials_to_remote_bootstrap(monkeypatch, tmp_path):
    monkeypatch.setattr(password_bootstrap.shutil, "which", lambda name: "/usr/bin/sshpass")
    monkeypatch.setenv("HOME", str(tmp_path))
    ssh_dir = Path(tmp_path) / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    key = ssh_dir / "xfi_guard_cluster_ed25519"
    pub = Path(str(key) + ".pub")
    key.write_text("PRIVATE", encoding="utf-8")
    pub.write_text("ssh-ed25519 AAAATEST xfi-guard\n", encoding="utf-8")

    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    captured = {}

    def fake_bootstrap(host, user, port, timeout, identity_file, **kwargs):
        captured.update(
            host=host,
            user=user,
            port=port,
            timeout=timeout,
            identity_file=identity_file,
            **kwargs,
        )
        return True, "XFI_GUARD_PROVISION_OK"

    monkeypatch.setattr(password_bootstrap.subprocess, "run", fake_run)
    monkeypatch.setattr(node_bootstrap, "bootstrap", fake_bootstrap)

    ok, output = password_bootstrap.bootstrap_with_password(
        "2.27.37.78",
        "root",
        22,
        "temporary-password",
        60,
        node_id="2.27.37.78",
        cluster_master="https://ger.deilja.online",
        cluster_secret="test-secret",
        cluster_token="test-token",
    )

    assert ok is True
    assert "XFI_GUARD_PROVISION_OK" in output
    assert captured == {
        "host": "2.27.37.78",
        "user": "root",
        "port": 22,
        "timeout": 60,
        "identity_file": str(key),
        "node_id": "2.27.37.78",
        "cluster_master": "https://ger.deilja.online",
        "cluster_secret": "test-secret",
        "cluster_token": "test-token",
    }
    assert calls[0][0:3] == ["sshpass", "-e", "ssh"]
    assert calls[1][0] == "chmod"
    assert calls[2][0] == "ssh"
