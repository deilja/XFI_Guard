"""Command-line interface for XFI Guard."""

from __future__ import annotations

import argparse
import json

from .checks import collect_basic_checks
from .security import collect_security_checks


def main() -> int:
    parser = argparse.ArgumentParser(prog="xfi-guard")
    parser.add_argument(
        "--scope",
        choices=("basic", "security", "all"),
        default="all",
        help="Checks to execute",
    )
    args = parser.parse_args()

    results = []
    if args.scope in {"basic", "all"}:
        results.extend(collect_basic_checks())
    if args.scope in {"security", "all"}:
        results.extend(collect_security_checks())

    print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
    return 0
