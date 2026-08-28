#!/usr/bin/env python3
"""Dependency-free static security gate for XFI Guard Python sources."""
from __future__ import annotations
import ast
import pathlib

ROOTS = (pathlib.Path("xfi_guard"), pathlib.Path("tests"))
EXCLUDED = {"__pycache__"}
SECRET_NAMES = {"API_KEY", "BOT_TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY", "TOKEN"}


def files():
    for root in ROOTS:
        if not root.exists():
            continue
        yield from (p for p in root.rglob("*.py") if not any(x in EXCLUDED for x in p.parts))


def _name_is_secret(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in SECRET_NAMES)


def _contains_secret_name(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and _name_is_secret(n.id) for n in ast.walk(node))


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
            if not isinstance(node, ast.Call):
                continue
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
            if isinstance(fn, ast.Name) and fn.id == "print":
                if any(_contains_secret_name(arg) for arg in node.args):
                    findings.append(f"{path}:{node.lineno}: possible secret passed to print()")
            if isinstance(fn, ast.Attribute) and fn.attr in {"debug", "info", "warning", "error", "exception", "critical"}:
                if any(_contains_secret_name(arg) for arg in node.args):
                    findings.append(f"{path}:{node.lineno}: possible secret passed to logger")

        # Flag local legacy plumbing, not the centralized admin_auth helper
        # itself. Reading the helper's admin list is the intended policy path.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "admin_ids" and isinstance(node.ctx, (ast.Store, ast.Del)):
                findings.append(f"{path}:{node.lineno}: legacy local admin_ids assignment")

    if findings:
        print("XFI Guard static security audit: FAILED")
        print("\n".join(f"- {x}" for x in findings))
        return 1
    print("XFI Guard static security audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
