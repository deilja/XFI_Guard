# XFI Guard

Security and monitoring toolkit for VPS infrastructure.

## Status

XFI Guard v1.0 is under active development.

## Current implementation

- Python package with versioned project metadata
- read-only disk and memory health checks
- availability checks for UFW, Fail2Ban and systemd tools
- safe systemd service status check
- JSON CLI output
- initial unit tests

Run locally:

```bash
python3 main.py
```

Or install the package and use:

```bash
xfi-guard
```

## Planned modules

- security event collection
- SSH authentication monitoring
- Xray / 3X-UI health checks
- structured audit logging
- Telegram notifications
- optional AI-assisted incident analysis
- alert thresholds and persistent state

## Design principles

- safe, read-only diagnostics by default
- explicit confirmation before destructive actions
- least-privilege operation
- secrets kept outside the repository
- clear audit trail for security actions
