"""Repository hardcoding audit helper.

Scans Python files for common hardcoded runtime knowledge patterns:
- Large uppercase dict/list constants
- Regex compile literals
- Provider/model literal strings
- Explicit fallback/default constants

Usage:
  python scripts/hardcoding_audit.py
  python scripts/hardcoding_audit.py --root . --min-collection-size 5 --json-out hardcoding_report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

UPPERCASE_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
PROVIDER_LITERAL_RE = re.compile(
    r"(openai/[\w\.-]+|deepgram/[\w\.-]+|cartesia/[\w\.-]+|groq/[\w\.-]+|gpt-[\w\.-]+|sonic-[\w\.-]+|nova-[\w\.-]+|mistral[\w\.-]+)",
    re.IGNORECASE,
)

DEFAULT_EXCLUDED_DIRS = {
    ".venv",
    "__pycache__",
    "site-packages",
    ".git",
    "docs",
}


def _collect_docstring_lines(tree: ast.AST) -> set[int]:
    """Collect line numbers occupied by module/class/function docstrings."""
    lines: set[int] = set()

    def _mark_docstring(node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            return
        first = body[0]
        if not isinstance(first, ast.Expr):
            return
        value = first.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            return
        start = getattr(value, "lineno", 0)
        end = getattr(value, "end_lineno", start)
        for i in range(start, end + 1):
            lines.add(i)

    _mark_docstring(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _mark_docstring(node)

    return lines


def _collection_size(node: ast.AST) -> int:
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        if isinstance(node, ast.Dict):
            return len(node.keys)
        return len(node.elts)
    return 0


def _literal_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _add_finding(findings: list[dict[str, Any]], file_path: Path, line: int, kind: str, detail: str) -> None:
    findings.append(
        {
            "file": str(file_path).replace("\\", "/"),
            "line": line,
            "kind": kind,
            "detail": detail,
        }
    )


def _scan_file(path: Path, min_collection_size: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return findings

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings

    docstring_lines = _collect_docstring_lines(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value_size = _collection_size(node.value)
            for target in node.targets:
                name = _target_name(target)
                if not name:
                    continue

                if UPPERCASE_NAME_RE.match(name) and value_size >= min_collection_size:
                    _add_finding(
                        findings,
                        path,
                        node.lineno,
                        "uppercase_collection",
                        f"{name} size={value_size}",
                    )

                if "FALLBACK" in name or "DEFAULT" in name:
                    _add_finding(
                        findings,
                        path,
                        node.lineno,
                        "fallback_default_constant",
                        name,
                    )

        if isinstance(node, ast.AnnAssign):
            name = _target_name(node.target)
            if name:
                value_size = _collection_size(node.value) if node.value else 0
                if UPPERCASE_NAME_RE.match(name) and value_size >= min_collection_size:
                    _add_finding(
                        findings,
                        path,
                        node.lineno,
                        "uppercase_collection",
                        f"{name} size={value_size}",
                    )

                if "FALLBACK" in name or "DEFAULT" in name:
                    _add_finding(
                        findings,
                        path,
                        node.lineno,
                        "fallback_default_constant",
                        name,
                    )

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "compile":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "re":
                    if node.args:
                        pattern = _literal_str(node.args[0])
                        if pattern is not None:
                            _add_finding(
                                findings,
                                path,
                                node.lineno,
                                "regex_literal",
                                pattern[:120],
                            )

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.lineno in docstring_lines:
                continue
            if PROVIDER_LITERAL_RE.search(node.value):
                _add_finding(
                    findings,
                    path,
                    node.lineno,
                    "provider_or_model_literal",
                    node.value[:120],
                )

    return findings


def _iter_python_files(root: Path, include_docs: bool = False) -> list[Path]:
    excluded_dirs = set(DEFAULT_EXCLUDED_DIRS)
    if include_docs:
        excluded_dirs.discard("docs")

    return [
        p
        for p in root.rglob("*.py")
        if not any(part in excluded_dirs for part in p.parts)
        and p.name != "hardcoding_audit.py"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan repository for hardcoding hotspots.")
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument("--min-collection-size", type=int, default=5)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--include-docs", action="store_true", help="Include docs/*.py in scan")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = _iter_python_files(root, include_docs=args.include_docs)

    all_findings: list[dict[str, Any]] = []
    for file_path in files:
        all_findings.extend(_scan_file(file_path, args.min_collection_size))

    all_findings.sort(key=lambda f: (f["file"], f["line"], f["kind"]))

    counts: dict[str, int] = {}
    for f in all_findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1

    print(f"Scanned files: {len(files)}")
    print(f"Findings: {len(all_findings)}")
    for kind, count in sorted(counts.items()):
        print(f"  {kind}: {count}")

    print("\nTop findings:")
    for f in all_findings[:60]:
        print(f"- {f['file']}:{f['line']} [{f['kind']}] {f['detail']}")

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.write_text(json.dumps(all_findings, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON report: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
