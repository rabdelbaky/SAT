"""Tests for the Go cover-profile reader and Go detection (Session 14).

`go test -coverprofile=coverage.out` writes a Go cover profile, NOT lcov:

    mode: set
    example.com/calc/calc.go:5.25,7.2 1 1      <file>:<start>,<end> <statements> <count>

Line coverage = statements in blocks with count > 0 / all statements.
There is no branch coverage in this format (branch_pct is None).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import read_coverage_file, read_project_coverage
from detection import detect_commands
from discovery import Project
from pre_llm_checks import load_languages


def _profile(tmp_path: Path, text: str, name: str = "coverage.out") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_set_mode_counts_statements_in_covered_blocks(tmp_path):
    p = _profile(
        tmp_path,
        "mode: set\n"
        "example.com/calc/calc.go:5.25,7.2 1 1\n"
        "example.com/calc/calc.go:9.20,12.2 3 0\n"
        "example.com/calc/other.go:3.10,4.2 4 1\n",
    )
    r = read_coverage_file(p)
    assert r is not None
    assert r.format == "gocover"
    assert r.line_pct == 62.5  # (1 + 4) / (1 + 3 + 4) statements
    assert r.branch_pct is None


def test_count_and_atomic_modes_use_hit_counts(tmp_path):
    for mode in ("count", "atomic"):
        d = tmp_path / mode
        d.mkdir()
        p = _profile(d, f"mode: {mode}\na.go:1.1,2.2 2 7\na.go:3.1,4.2 2 0\n")
        assert read_coverage_file(p).line_pct == 50.0


def test_fully_covered_is_100(tmp_path):
    r = read_coverage_file(_profile(tmp_path, "mode: set\na.go:1.1,2.2 3 1\n"))
    assert r.line_pct == 100.0


def test_profile_with_no_blocks_is_unreadable(tmp_path):
    assert read_coverage_file(_profile(tmp_path, "mode: set\n")) is None


def test_empty_and_garbage_are_unreadable(tmp_path):
    assert read_coverage_file(_profile(tmp_path, "")) is None
    d = tmp_path / "g"
    d.mkdir()
    assert read_coverage_file(_profile(d, "this is not a cover profile\nDA:1,1\n")) is None


def test_malformed_block_lines_are_skipped_not_fatal(tmp_path):
    p = _profile(tmp_path, "mode: set\nbroken line\na.go:1.1,2.2 2 1\na.go:3.1,4.2 x y\n")
    r = read_coverage_file(p)
    assert r is not None and r.line_pct == 100.0


def test_duplicate_blocks_count_once_covered_if_any_line_hit(tmp_path):
    # e.g. -coverpkg=./...: each package's test run lists every block again.
    p = _profile(
        tmp_path,
        "mode: set\n"
        "a.go:1.1,2.2 1 1\n"
        "a.go:3.1,4.2 1 0\n"
        "a.go:1.1,2.2 1 0\n"
        "a.go:3.1,4.2 1 1\n",
    )
    assert read_coverage_file(p).line_pct == 100.0


def test_fresh_go_profile_is_used_by_project_reader(tmp_path):
    f = _profile(tmp_path, "mode: set\na.go:1.1,2.2 4 1\na.go:3.1,4.2 1 0\n")
    start = time.time()
    os.utime(f, (start + 1, start + 1))
    data = read_project_coverage(tmp_path, ["coverage.out"], start, [])
    assert [(r.format, r.line_pct) for r in data.results] == [("gocover", 80.0)]
    assert data.warnings == []


def test_stale_go_profile_is_ignored(tmp_path):
    f = _profile(tmp_path, "mode: set\na.go:1.1,2.2 4 1\n")
    start = time.time()
    os.utime(f, (start - 100, start - 100))
    data = read_project_coverage(tmp_path, ["coverage.out"], start, [])
    assert data.results == [] and "coverage_stale" in data.warnings


# --- Go detection -------------------------------------------------------------

_GO = load_languages()["go"]


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def _go_project(tmp_path: Path, extra: dict[str, str] | None = None) -> Project:
    (tmp_path / "go.mod").write_text("module example.com/x\n\ngo 1.18\n")
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="go", primary_build_file="go.mod")


def test_bare_go_module_uses_toolchain_builtins(tmp_path):
    r = detect_commands(_go_project(tmp_path), _GO)
    assert _argv(r, "build") == [["go", "build", "-o", "/dev/null", "./..."]]
    assert _argv(r, "lint") == [["go", "vet", "./..."]]
    assert _argv(r, "tests") == [["go", "test", "./..."]]
    assert _argv(r, "coverage") == [["go", "test", "-coverprofile=coverage.out", "./..."]]


def test_golangci_config_replaces_go_vet_as_the_linter(tmp_path):
    r = detect_commands(_go_project(tmp_path, {".golangci.yml": "run: {}"}), _GO)
    assert _argv(r, "lint") == [["golangci-lint", "run", "--fix=false"]]
    assert r.commands["lint"][0].source == "config"
    assert _argv(r, "tests") == [["go", "test", "./..."]]


def test_go_has_no_dead_stage_names_or_config_files_tables():
    assert "stage_names" not in _GO
    assert "config_files" not in _GO
