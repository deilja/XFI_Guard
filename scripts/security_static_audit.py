#!/usr/bin/env python3
"""Small dependency-free static security gate for XFI Guard Python sources."""
from __future__ import annotations
import ast
import pathlib
import re
import sys

ROOTS = (pathlib.Path("xfi_guard"), pathlib.Path("tests"))
EXCLUDED = {"__pycache__"}


def files():
    for root in ROOTS:
        if not root.exists():
            continue
        yield from (p for p in root.rglob("*.py") if not any(x in EXCLUDED for x in p.parts))


def main() -> int:
    findings: list[str] = []
    for path in files():
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(f"{path}: cannot parse: {exc}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in {"eval", "exec"}:
                    findings.append(f"{path}:{node.lineno}: forbidden {fn.id}()")
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    if fn.value.id == "os" and fn.attr == "system":
                        findings.append(f"{path}:{node.lineno}: forbidden os.system()")
                    if fn.value.id == "pickle" and fn.attr in {"load", "loads"}:
                        findings.append(f"{path}:{node.lineno}: forbidden pickle.{fn.attr}()")
                    if fn.value.id == "yaml" and fn.attr == "load":
                        findings.append(f"{path}:{node.lineno}: unsafe yaml.load()")
                if isinstance(fn, ast.Attribute) and fn.attr in {"run", "Popen", "call", "check_call", "check_output"}:
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            findings.append(f"{path}:{node.lineno}: subprocess shell=True")

        # Legacy authorization and obvious credential leakage patterns.
        if re.search(r"\badmin_ids\b|from_user\.id\s*(?:not\s+in|in)\s+", text):
            findings.append(f"{path}: legacy/direct Telegram authorization pattern")
        if re.search(r"(?:print|logger\.(?:debug|info|warning|error|exception))\s*\([^\n]*(?:API_KEY|BOT_TOKEN|PASSWORD|SECRET|PRIVATE_KEY)", text, re.I):
            findings.append(f"{path}: possible secret logging")

    if findings:
        print("XFI Guard static security audit: FAILED")
        print("\n".join(f"- {x}" for x in findings))
        return 1
    print("XFI Guard static security audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
