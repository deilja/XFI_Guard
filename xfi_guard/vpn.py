"""Проверка фактического состояния 3X-UI/Xray и сетевых портов + API-мониторинг."""
from __future__ import annotations

import os
import re
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .checks import CheckResult, _run

XRAY_RE = re.compile(
    r"(?:^|[\s/])(xray|xray-linux(?:-amd64|-arm64|-arm)?)(?:$|[\s])",
    re.IGNORECASE,
)


class XUIApiClient:
    """Лёгкий клиент 3X-UI API: Bearer token или login/password."""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        web_base_path: str = "/",
        verify_ssl: bool = True,
        timeout: float = 8.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.web_base_path = web_base_path or "/"
        if not self.web_base_path.startswith("/"):
            self.web_base_path = f"/{self.web_base_path}"
        if self.web_base_path != "/":
            self.web_base_path = self.web_base_path.rstrip("/")
        self.token = token or os.getenv("XUI_TOKEN")
        self.username = username or os.getenv("XUI_USERNAME")
        self.password = password or os.getenv("XUI_PASSWORD")
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.4,
            status_forcelist=(502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        self._logged_in = bool(self.token)

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{self.web_base_path}{path}"

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except (ValueError, requests.RequestException):
            return {"success": False, "msg": f"HTTP {response.status_code}"}
        return data if isinstance(data, dict) else {"success": False, "msg": "Invalid JSON response"}

    def login(self) -> bool:
        if self.token:
            self._logged_in = True
            return True
        if not (self.username and self.password):
            self._logged_in = False
            return False
        try:
            response = self.session.post(
                self._url("/login"),
                data={"username": self.username, "password": self.password},
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            data = self._json(response)
            self._logged_in = response.ok and bool(data.get("success"))
            return self._logged_in
        except requests.RequestException:
            self._logged_in = False
            return False

    def get(self, path: str) -> dict[str, Any]:
        if not self._logged_in and not self.login():
            return {"success": False, "msg": "auth failed"}
        try:
            response = self.session.get(self._url(path), timeout=self.timeout, verify=self.verify_ssl)
            if response.status_code in (401, 403) and not self.token:
                self._logged_in = False
                if self.login():
                    response = self.session.get(self._url(path), timeout=self.timeout, verify=self.verify_ssl)
            return self._json(response)
        except requests.RequestException as exc:
            return {"success": False, "msg": str(exc)}

    def post(self, path: str, json_data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if not self._logged_in and not self.login():
            return {"success": False, "msg": "auth failed"}
        try:
            response = self.session.post(
                self._url(path), json=json_data or {}, timeout=self.timeout, verify=self.verify_ssl
            )
            if response.status_code in (401, 403) and not self.token:
                self._logged_in = False
                if self.login():
                    response = self.session.post(
                        self._url(path), json=json_data or {}, timeout=self.timeout, verify=self.verify_ssl
                    )
            return self._json(response)
        except requests.RequestException as exc:
            return {"success": False, "msg": str(exc)}

    def post_form(self, path: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """POST с form-urlencoded; используется для endpoints logs/xraylogs."""
        if not self._logged_in and not self.login():
            return {"success": False, "msg": "auth failed"}
        payload = data or {}
        try:
            response = self.session.post(
                self._url(path), data=payload, timeout=self.timeout, verify=self.verify_ssl
            )
            if response.status_code in (401, 403) and not self.token:
                self._logged_in = False
                if self.login():
                    response = self.session.post(
                        self._url(path), data=payload, timeout=self.timeout, verify=self.verify_ssl
                    )
            return self._json(response)
        except requests.RequestException as exc:
            return {"success": False, "msg": str(exc)}


def _get_api_client() -> Optional[XUIApiClient]:
    """Создаёт API-клиент только если XUI_HOST задан."""
    host = os.getenv("XUI_HOST")
    if not host:
        return None
    return XUIApiClient(
        base_url=host,
        token=os.getenv("XUI_TOKEN"),
        username=os.getenv("XUI_USERNAME"),
        password=os.getenv("XUI_PASSWORD"),
        web_base_path=os.getenv("XUI_WEBBASEPATH", "/"),
        verify_ssl=os.getenv("XUI_VERIFY_SSL", "true").lower() not in {"0", "false", "no"},
        timeout=float(os.getenv("XUI_API_TIMEOUT", "8")),
    )


def _xray_processes() -> list[str]:
    code, stdout, _ = _run(["ps", "-eo", "pid=,comm=,args="])
    if code != 0:
        return []
    matches: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        comm = parts[1] if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else ""
        if comm.lower() in {"xray", "xray-linux-amd64", "xray-linux-arm64", "xray-linux-arm"} or XRAY_RE.search(args):
            matches.append(line)
    return matches


def check_xray_runtime() -> CheckResult:
    matches = _xray_processes()
    if matches:
        return CheckResult("xray_runtime", "ok", "Xray реально запущен и работает как процесс", {"processes": matches})
    return CheckResult("xray_runtime", "critical", "Процесс Xray не запущен", {})


def check_panel_service(services: tuple[str, ...] = ("x-ui", "3x-ui")) -> CheckResult:
    states = []
    for service in services:
        code, stdout, _ = _run(["systemctl", "is-active", service])
        if code == 0 and stdout.strip() == "active":
            states.append(service)
    if states:
        return CheckResult("xui_panel", "ok", f"Панель управления активна: {', '.join(states)}", {"services": states})
    return CheckResult("xui_panel", "warning", "Служба 3X-UI/x-ui не найдена среди активных systemd-сервисов", {})


def check_service_candidates(services: tuple[str, ...] = ("xray", "x-ui", "3x-ui")) -> list[CheckResult]:
    raw = []
    for service in services:
        code, stdout, stderr = _run(["systemctl", "is-active", service])
        state = stdout.strip()
        if code == 0 and state == "active":
            raw.append((service, "ok", state))
        elif state in {"inactive", "failed"}:
            raw.append((service, "critical", state))
        else:
            raw.append((service, "unknown", state or stderr.strip()))
    xray_runtime = bool(_xray_processes())
    panel_active = any(service in {"x-ui", "3x-ui"} and status == "ok" for service, status, _ in raw)
    results = []
    for service, status, output in raw:
        if service == "xray" and xray_runtime:
            status = "ok"
            message = "Xray работает (фактический процесс активен)"
        elif service == "xray" and panel_active and status == "critical":
            status = "warning"
            message = "Отдельный systemd-сервис Xray неактивен, но панель 3X-UI/x-ui работает; проверяйте фактический процесс выше"
        elif service == "3x-ui" and panel_active and status == "critical":
            status = "warning"
            message = "Сервис 3x-ui неактивен, но активна панель x-ui"
        elif status == "ok":
            message = f"Сервис {service} активен"
        elif status == "critical":
            message = f"Сервис {service} неактивен"
        else:
            message = f"Состояние сервиса {service} недоступно"
        results.append(CheckResult("vpn_service", status, message, {"service": service, "output": output}))
    return results


def check_listening_ports(ports: tuple[int, ...] = (22, 80, 443, 2053, 2083, 2087, 2096)) -> CheckResult:
    code, stdout, stderr = _run(["ss", "-lntup"])
    if code != 0:
        return CheckResult("network", "unknown", "Не удалось проверить открытые сетевые порты", {"output": stdout or stderr})
    listeners: list[dict[str, Any]] = []
    for line in stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5:
            continue
        local = fields[3]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        if port_text.isdigit() and int(port_text) in ports:
            match = re.search(r'users:\(\("([^"]+)"', line)
            process = match.group(1) if match else ""
            listeners.append({"port": int(port_text), "process": process, "line": line})
    return CheckResult("network", "ok", f"Обнаружено {len(listeners)} отслеживаемых открытых портов", {"listeners": listeners, "monitored_ports": list(ports)})


def check_api_server_status(client: Optional[XUIApiClient] = None) -> CheckResult:
    client = client or _get_api_client()
    if client is None:
        return CheckResult("api_server_status", "unknown", "XUI_HOST не задан — API-проверка пропущена", {})
    data = client.get("/panel/api/server/status")
    if not data.get("success"):
        return CheckResult("api_server_status", "critical", f"API status недоступен: {data.get('msg', 'unknown error')}", {"raw": data})
    obj = data.get("obj") or {}
    xray = obj.get("xray") or {}
    state = str(xray.get("state") or "").lower()
    version = xray.get("version", "")
    error_msg = xray.get("errorMsg") or ""
    details = {"cpu": obj.get("cpu"), "mem": obj.get("mem"), "disk": obj.get("disk"), "uptime": obj.get("uptime"), "loads": obj.get("loads"), "tcpCount": obj.get("tcpCount"), "udpCount": obj.get("udpCount"), "netIO": obj.get("netIO"), "xray": xray}
    if state == "running":
        return CheckResult("api_server_status", "ok", f"Xray running (API), version={version}", details)
    if state in {"stop", "stopped"}:
        return CheckResult("api_server_status", "critical", f"Xray stopped (API): {error_msg or 'no error msg'}", details)
    return CheckResult("api_server_status", "warning", f"Xray state={state or 'unknown'} (API): {error_msg}", details)


def check_api_online_clients(client: Optional[XUIApiClient] = None) -> CheckResult:
    client = client or _get_api_client()
    if client is None:
        return CheckResult("api_online_clients", "unknown", "XUI_HOST не задан — API-проверка пропущена", {})
    data = client.post("/panel/api/clients/onlines")
    if not data.get("success"):
        data = client.get("/panel/api/clients/onlines")
    if not data.get("success"):
        return CheckResult("api_online_clients", "warning", f"Не удалось получить online-клиентов: {data.get('msg', 'error')}", {"raw": data})
    online = data.get("obj") or []
    if isinstance(online, dict):
        online = list(online.keys())
    count = len(online) if isinstance(online, list) else 0
    return CheckResult("api_online_clients", "ok", f"Online клиентов: {count}", {"count": count})


def check_api_inbounds_summary(client: Optional[XUIApiClient] = None) -> CheckResult:
    client = client or _get_api_client()
    if client is None:
        return CheckResult("api_inbounds", "unknown", "XUI_HOST не задан — API-проверка пропущена", {})
    data = client.get("/panel/api/inbounds/list")
    if not data.get("success"):
        return CheckResult("api_inbounds", "warning", f"Не удалось получить inbounds: {data.get('msg', 'error')}", {"raw": data})
    inbounds = data.get("obj") or []
    if not isinstance(inbounds, list):
        return CheckResult("api_inbounds", "warning", "API вернул некорректный список inbounds", {"raw": data})
    total = len(inbounds)
    enabled = sum(1 for item in inbounds if item.get("enable"))
    protocols: dict[str, int] = {}
    for item in inbounds:
        protocol = str(item.get("protocol") or "unknown").lower()
        protocols[protocol] = protocols.get(protocol, 0) + 1
    return CheckResult("api_inbounds", "ok", f"Inbounds: {enabled}/{total} enabled", {"total": total, "enabled": enabled, "protocols": protocols})


_XRAY_ERROR_RE = re.compile(r"(?i)(error|fatal|panic|failed|exception|cannot|unable|refused|timeout|denied)")
_XRAY_WARN_RE = re.compile(r"(?i)(warning|warn|deprecated)")


def check_api_xray_logs(
    client: Optional[XUIApiClient] = None,
    count: int = 100,
    filter_text: str = "",
) -> CheckResult:
    """Проверяет последние Xray access/log записи через 3X-UI API."""
    client = client or _get_api_client()
    if client is None:
        return CheckResult("api_xray_logs", "unknown", "XUI_HOST не задан — API-проверка логов пропущена", {})
    count = max(1, min(int(count), 1000))
    form = {"showDirect": "true", "showBlocked": "true", "showProxy": "true"}
    if filter_text:
        form["filter"] = filter_text
    data = client.post_form(f"/panel/api/server/xraylogs/{count}", form)
    if not data.get("success"):
        return CheckResult("api_xray_logs", "warning", f"Не удалось получить xraylogs: {data.get('msg', 'error')}", {"raw": data})
    entries = data.get("obj") or []
    if not isinstance(entries, list):
        entries = []
    errors: list[str] = []
    warnings: list[str] = []
    sample: list[Any] = []
    for entry in entries:
        if isinstance(entry, dict):
            text = " ".join(str(v) for v in entry.values())
            sample.append(entry)
        else:
            text = str(entry)
            sample.append(text)
        if _XRAY_ERROR_RE.search(text):
            errors.append(text[:300])
        elif _XRAY_WARN_RE.search(text):
            warnings.append(text[:300])
    details = {"total_entries": len(entries), "errors_count": len(errors), "warnings_count": len(warnings), "errors": errors[:10], "warnings": warnings[:10], "sample": sample[:5]}
    if errors:
        return CheckResult("api_xray_logs", "critical", f"В логах Xray найдено {len(errors)} ошибок (из {len(entries)} записей)", details)
    if warnings:
        return CheckResult("api_xray_logs", "warning", f"В логах Xray найдено {len(warnings)} предупреждений (из {len(entries)} записей)", details)
    return CheckResult("api_xray_logs", "ok", f"Логи Xray без ошибок ({len(entries)} записей)", details)


def check_api_panel_logs(
    client: Optional[XUIApiClient] = None,
    count: int = 80,
    level: str = "warning",
) -> CheckResult:
    """Проверяет логи панели 3X-UI через POST /panel/api/server/logs/{count}."""
    client = client or _get_api_client()
    if client is None:
        return CheckResult("api_panel_logs", "unknown", "XUI_HOST не задан — API-проверка логов пропущена", {})
    count = max(1, min(int(count), 1000))
    allowed_levels = {"debug", "info", "notice", "warning", "error"}
    level = level.lower() if level.lower() in allowed_levels else "warning"
    data = client.post_form(f"/panel/api/server/logs/{count}", {"level": level, "syslog": "false"})
    if not data.get("success"):
        return CheckResult("api_panel_logs", "warning", f"Не удалось получить panel logs: {data.get('msg', 'error')}", {"raw": data})
    lines = data.get("obj") or []
    if not isinstance(lines, list):
        lines = [str(lines)]
    errors: list[str] = []
    warnings: list[str] = []
    xray_related: list[str] = []
    for line in lines:
        text = str(line)
        if "xray" in text.lower():
            xray_related.append(text[:300])
        if _XRAY_ERROR_RE.search(text):
            errors.append(text[:300])
        elif _XRAY_WARN_RE.search(text):
            warnings.append(text[:300])
    details = {"total_lines": len(lines), "errors_count": len(errors), "warnings_count": len(warnings), "xray_related_count": len(xray_related), "errors": errors[:10], "warnings": warnings[:10], "xray_sample": xray_related[:5]}
    if errors:
        return CheckResult("api_panel_logs", "critical", f"В логах панели найдено {len(errors)} ошибок (level≥{level})", details)
    if warnings:
        return CheckResult("api_panel_logs", "warning", f"В логах панели найдено {len(warnings)} предупреждений", details)
    return CheckResult("api_panel_logs", "ok", f"Логи панели без ошибок ({len(lines)} строк, level={level})", details)


def check_local_xray_logs(
    log_paths: tuple[str, ...] = (
        "/var/log/x-ui/xray.log",
        "/var/log/xray/access.log",
        "/usr/local/x-ui/bin/access.log",
        "/usr/local/x-ui/bin/error.log",
        "./access.log",
    ),
    tail_lines: int = 100,
) -> CheckResult:
    """Читает последние строки локальных логов Xray как fallback."""
    found_path = None
    content = ""
    tail_lines = max(1, min(int(tail_lines), 2000))
    for path in log_paths:
        if os.path.isfile(path):
            found_path = path
            try:
                code, stdout, _ = _run(["tail", "-n", str(tail_lines), path])
                if code == 0:
                    content = stdout
                    break
            except Exception:
                continue
    if not found_path or not content:
        return CheckResult("local_xray_logs", "unknown", "Локальные логи Xray не найдены", {"tried_paths": list(log_paths)})
    lines = content.splitlines()
    errors = [ln[:300] for ln in lines if _XRAY_ERROR_RE.search(ln)]
    warnings = [ln[:300] for ln in lines if _XRAY_WARN_RE.search(ln)]
    details = {"path": found_path, "lines": len(lines), "errors_count": len(errors), "warnings_count": len(warnings), "errors": errors[:10], "warnings": warnings[:10]}
    if errors:
        return CheckResult("local_xray_logs", "critical", f"В {found_path} найдено {len(errors)} ошибок", details)
    if warnings:
        return CheckResult("local_xray_logs", "warning", f"В {found_path} найдено {len(warnings)} предупреждений", details)
    return CheckResult("local_xray_logs", "ok", f"Локальные логи Xray без ошибок ({found_path})", details)


def collect_vpn_checks(
    include_api: bool = True,
    include_logs: bool = True,
    include_local_log_fallback: bool = True,
    ports: tuple[int, ...] = (22, 80, 443, 2053, 2083, 2087, 2096),
) -> list[CheckResult]:
    """Собирает локальные проверки, API 3X-UI и проверки логов."""
    results: list[CheckResult] = [check_panel_service(), check_xray_runtime()]
    results.extend(check_service_candidates())
    results.append(check_listening_ports(ports))
    if include_api:
        client = _get_api_client()
        results.append(check_api_server_status(client))
        results.append(check_api_online_clients(client))
        results.append(check_api_inbounds_summary(client))
        if include_logs:
            results.append(check_api_xray_logs(client))
            results.append(check_api_panel_logs(client))
    if include_local_log_fallback:
        results.append(check_local_xray_logs())
    return results
