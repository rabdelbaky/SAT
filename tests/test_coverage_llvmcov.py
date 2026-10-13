"""Tests for the llvm-cov JSON reader (Session 19).

`swift test --enable-code-coverage` writes an llvm-cov JSON export to
.build/<platform>/debug/codecov/<package>.json:

    {"type": "llvm.coverage.json.export", "version": "2.0.1",
     "data": [{"files": [{"filename": "/abs/Sources/Calc/Calc.swift",
                          "summary": {"lines": {"count": 9, "covered": 3, ...}, ...}},
                         ...],
               "totals": {...}}]}

Only the package's own sources count: not Tests/ (the test targets), not
.build/ (SwiftPM's generated test runner), not files outside the project.
The export's own totals mix those in, so they are not used.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import _detect_format, read_coverage_file, read_project_coverage

_PLATFORM = "x86_64-unknown-linux-gnu"


def _entry(path: Path, count: int, covered: int) -> dict:
    return {
        "filename": str(path),
        "summary": {
            "lines": {"count": count, "covered": covered, "percent": covered / count * 100},
            "branches": {"count": 0, "covered": 0, "notcovered": 0, "percent": 0},
        },
    }


def _export(tmp_path: Path, extra: list[tuple[str, int, int]] | None = None, *,
            only_tests: bool = False) -> dict:
    proj = tmp_path / "proj"
    files = [
        (proj / "Tests" / "CalcTests" / "CalcTests.swift", 5, 5),
        (proj / ".build" / _PLATFORM / "debug" / "pkgPackageTests.derived" / "runner.swift", 174, 26),
    ]
    if not only_tests:
        files.insert(0, (proj / "Sources" / "Calc" / "Calc.swift", 9, 3))
        files.append((tmp_path / "other" / "Dep.swift", 10, 10))
    for rel, count, covered in extra or []:
        files.append((proj / rel, count, covered))
    return {
        "type": "llvm.coverage.json.export",
        "version": "2.0.1",
        "data": [{
            "files": [_entry(p, n, c) for p, n, c in files],
            "totals": {"lines": {"count": 201, "covered": 47, "percent": 23.38}},
        }],
    }


def _write(tmp_path: Path, data, folder: Path | None = None) -> Path:
    d = folder or tmp_path / "proj" / ".build" / _PLATFORM / "debug" / "codecov"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "pkg.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return p


def test_counts_only_the_package_sources(tmp_path):
    r = read_coverage_file(_write(tmp_path, _export(tmp_path)))
    assert r is not None
    # not 23.38: the export's totals are not used
    assert (r.line_pct, r.branch_pct, r.format) == (33.33, None, "llvmcov")


def test_several_source_files_add_up(tmp_path):
    data = _export(tmp_path, [("Sources/Calc/More.swift", 1, 1)])
    r = read_coverage_file(_write(tmp_path, data))
    assert r is not None and r.line_pct == 40.0


def test_unreadable_variants_return_none(tmp_path):
    good = _export(tmp_path)
    no_type = {k: v for k, v in good.items() if k != "type"}
    variants = [
        no_type,
        {**good, "type": "other"},
        {**good, "data": []},
        _export(tmp_path, only_tests=True),
        "not json",
    ]
    for i, content in enumerate(variants):
        d = tmp_path / "proj" / ".build" / str(i) / "debug" / "codecov"
        assert read_coverage_file(_write(tmp_path, content, d)) is None, i


def test_file_outside_a_build_folder_returns_none(tmp_path):
    p = _write(tmp_path, _export(tmp_path), tmp_path / "proj" / "codecov")
    assert read_coverage_file(p) is None


def test_detect_format():
    assert _detect_format(Path(".build/x/debug/codecov/pkg.json")) == "llvmcov"
    assert _detect_format(Path("coverage-summary.json")) == "istanbul"
    assert _detect_format(Path("codecov.json")) == "unknown"


def test_fresh_and_stale_through_project_reader(tmp_path):
    p = _write(tmp_path, _export(tmp_path))
    proj = tmp_path / "proj"
    start = time.time()
    os.utime(p, (start + 1, start + 1))
    data = read_project_coverage(proj, [".build/*/debug/codecov/*.json"], start, [])
    assert len(data.results) == 1
    assert data.results[0].source_file.endswith("pkg.json")
    os.utime(p, (start - 100, start - 100))
    data = read_project_coverage(proj, [".build/*/debug/codecov/*.json"], start, [])
    assert data.results == [] and "coverage_stale" in data.warnings
