"""Stdlib 'linter' for the python-* fixtures: every .py file must parse.
Exit 1 and print the error when one does not. Writes no files."""
import ast
import pathlib
import sys

failed = False
for p in sorted(pathlib.Path(".").glob("*.py")):
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except SyntaxError as exc:
        print(f"{p}:{exc.lineno}: syntax error: {exc.msg}")
        failed = True
sys.exit(1 if failed else 0)
