"""Daemon entry point for XFI Guard."""

from __future__ import annotations

import argparse
import logging

from .config import load_config
from .monitor import run_forever


def main() -> int:
    parser = argparse.ArgumentParser(prog="xfi-guard-daemon")
    parser.add_argument("--config", default="config.toml", help="Path to TOML configuration")
    args = parser.parse_args()
    config = load_config(args.config)
    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
