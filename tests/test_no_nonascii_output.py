"""Guards against non-ASCII characters reaching a console via print(),
raise <Exception>(...), or logger.*() calls -- the mechanism that let a
stray em-dash mojibake harness/run_all.py's own headline summary line
under a native cp1252 PowerShell console (see CLAUDE.md). Docstrings and
comments are intentionally out of scope: they only ever reach a human
reading source, never a console encoding, and this project's convention
is to allow em-dashes and similar there freely.

AST-based rather than a line-proximity grep: it only flags a string
literal that is structurally an argument to one of these calls, so
docstrings/comments are excluded by construction, not by pattern-
matching around them.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCAN_DIRS = ["src", "scripts", "harness", "tests"]
SINK_LOGGER_METHODS = {"debug", "info", "warning", "error", "critical", "exception"}


def _iter_py_files():
    for d in SCAN_DIRS:
        for path in Path(d).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _is_sink_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "print":
        return True
    if isinstance(func, ast.Attribute) and func.attr in SINK_LOGGER_METHODS:
        return True
    return False


def _non_ascii_chars(s: str) -> str:
    return "".join(sorted({c for c in s if ord(c) > 127}))


def _check_string_node(node: ast.expr, path: Path, violations: list[str]) -> None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        bad = _non_ascii_chars(node.value)
        if bad:
            violations.append(f"{path}:{node.lineno}: non-ASCII {bad!r} in {node.value[:60]!r}")
    elif isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                bad = _non_ascii_chars(value.value)
                if bad:
                    violations.append(
                        f"{path}:{node.lineno}: non-ASCII {bad!r} in f-string segment {value.value[:60]!r}"
                    )
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        _check_string_node(node.left, path, violations)
        _check_string_node(node.right, path, violations)


def _scan_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_sink_call(node):
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                _check_string_node(arg, path, violations)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for arg in list(node.exc.args) + [kw.value for kw in node.exc.keywords]:
                _check_string_node(arg, path, violations)
    return violations


def test_no_non_ascii_reaches_print_raise_or_logger():
    """A non-ASCII character (e.g. an em-dash) in a string literal that
    is actually passed to print()/raise <Exc>(...)/logger.*() can
    mojibake under a native-encoding console (cp1252 here). Docstrings
    and bare comments never reach that path and are not scanned -- see
    module docstring."""
    all_violations: list[str] = []
    for path in _iter_py_files():
        all_violations.extend(_scan_file(path))
    assert not all_violations, "\n" + "\n".join(all_violations)
