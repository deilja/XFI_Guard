"""Command-line interface for XFI Guard."""

from __future__ import annotations

import json

from .checks import collect_basic_checks


def main() -> int:
    payload = [item.to_dict() for item in collect_basic_checks()]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
