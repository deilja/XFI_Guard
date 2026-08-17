# XFI Guard

Security and monitoring toolkit for VPS infrastructure.

## Status

XFI Guard v1.0 is under active development.

## Current implementation

- Python package with versioned project metadata
- read-only disk and memory health checks
- UFW, Fail2Ban and SSH security checks
- Xray / x-ui / 3x-ui service checks
- monitored listening-port checks
- JSON CLI output
- centralized TOML configuration
- continuous JSONL monitoring loop
- systemd service template
- unit tests and GitHub Actions CI

## Run locally

```bash
python3 main.py --scope all
```

Run the continuous monitor:

```bash
python3 -m xfi_guard.daemon --config config.toml
```

## Install as a systemd service

The service template is in `systemd/xfi-guard.service`. It expects the project at `/opt/xfi-guard` and writes monitoring records to `/var/log/xfi-guard/monitor.jsonl`.

## Configuration

Edit `config.toml` to change monitoring interval, warning thresholds, VPN service names and monitored ports. No secrets are stored in the repository.

## Planned modules

- structured security event collection
- SSH authentication event parser
- persistent state and alert deduplication
- Telegram notifications
- optional AI-assisted incident analysis
- controlled remediation actions

## Design principles

- safe, read-only diagnostics by default
- explicit confirmation before destructive actions
- least-privilege operation
- secrets kept outside the repository
- clear audit trail for security actions
