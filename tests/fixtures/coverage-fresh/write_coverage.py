"""Writes a fresh Cobertura XML coverage file. Used by coverage-fresh fixture."""

import pathlib

xml = (
    '<?xml version="1.0" ?>'
    '<coverage version="7.4.0"'
    ' lines-valid="100" lines-covered="72" line-rate="0.72"'
    ' branches-covered="13" branches-valid="20" branch-rate="0.65"'
    ' complexity="0">'
    "<packages/>"
    "</coverage>"
)
pathlib.Path("coverage.xml").write_text(xml, encoding="utf-8")
print("coverage.xml written")
