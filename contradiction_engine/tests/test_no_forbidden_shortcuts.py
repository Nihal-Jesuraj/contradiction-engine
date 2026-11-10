"""Guard: algorithm code must not use forbidden shortcuts."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]

FORBIDDEN_MODULES = {
    "bisect",
    "heapq",
    "intervaltree",
    "networkx",
    "scipy",
    "sortedcontainers",
    # Pandas and Streamlit belong to the display layer only.
    "pandas",
    "streamlit",
}

TARGETS = [
    PACKAGE / "algorithms",
    PACKAGE / "detectors",
    PACKAGE / "models.py",
    PACKAGE / "generator.py",
    PACKAGE / "loader.py",
]


def iter_source_files() -> list[Path]:
    """Return every Python file that holds algorithm logic."""
    files: list[Path] = []
    for target in TARGETS:
        if target.is_dir():
            files.extend(target.rglob("*.py"))
        elif target.is_file():
            files.append(target)
    return files


def test_no_forbidden_imports_or_builtin_sorting() -> None:
    """Reject banned modules and calls to sorted()/list.sort()."""
    offenders: list[str] = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN_MODULES:
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    offenders.append(f"{path}: from {node.module}")
            elif isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Name) and function.id == "sorted":
                    offenders.append(f"{path}: sorted() call")
                elif isinstance(function, ast.Attribute) and function.attr == "sort":
                    offenders.append(f"{path}: .sort() call")
    assert offenders == [], "forbidden shortcuts:\n" + "\n".join(offenders)
