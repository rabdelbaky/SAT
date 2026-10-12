"""Tests for coverage_readers.py and the coverage wiring in orchestrator.py (Session 8).

Seams under test
----------------
1. read_coverage_file(path) -> CoverageResult | None
2. parse_coverage_from_output(text) -> float | None
3. read_project_coverage(project_path, coverage_files, stage_start_time, output_texts)
4. CoverageData.lowest_line_pct()
5. orchestrator.run_project(...) coverage stage + project_results_to_report_data(...)

Fixtures are copied to a temp folder so the repo is never polluted and every
file has a known mtime.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import (
    CoverageData,
    CoverageResult,
    parse_coverage_from_output,
    read_coverage_file,
    read_project_coverage,
)
from detection import DetectionResult, StageCommand
from discovery import Project
from orchestrator import (
    OrchestratorOptions,
    ProjectResult,
    StageResult,
    project_results_to_report_data,
    run_project,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_SAMPLES = _FIXTURES / "coverage-samples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch(path: Path, mtime: float) -> Path:
    os.utime(path, (mtime, mtime))
    return path


def _copy_sample(name: str, dest_dir: Path, dest_name: str | None = None) -> Path:
    dest = dest_dir / (dest_name or name)
    shutil.copyfile(_SAMPLES / name, dest)
    return dest


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    dest = tmp_path / name
    shutil.copytree(_FIXTURES / name, dest)
    return dest


def _py_project(path: Path) -> Project:
    return Project(path=path, language="python", primary_build_file="pyproject.toml")


def _detection(stage_cmds: dict[str, list[list[str]]]) -> DetectionResult:
    return DetectionResult(
        commands={
            stage: [StageCommand(command=c, source="override") for c in cmds]
            for stage, cmds in stage_cmds.items()
        }
    )


def _run(
    project_path: Path,
    stage_cmds: dict[str, list[list[str]]],
    coverage_files: list[str],
    tmp_path: Path,
    stages: list[str] | None = None,
) -> ProjectResult:
    lang_cfg = {
        "stages": ["build", "lint", "tests", "coverage"],
        "coverage_files": coverage_files,
    }
    opts = OrchestratorOptions(steps=stages or ["coverage"])
    return run_project(
        project=_py_project(project_path),
        lang_cfg=lang_cfg,
        detection=_detection(stage_cmds),
        opts=opts,
        log_dir=tmp_path / "logs",
        repo_root=tmp_path,
    )


def _coverage_stage(result: ProjectResult) -> StageResult:
    return next(s for s in result.stages if s.stage == "coverage")


# ---------------------------------------------------------------------------
# 1. Each format parses to the expected numbers
# ---------------------------------------------------------------------------


def test_jacoco_line_and_branch():
    r = read_coverage_file(_SAMPLES / "jacoco.xml")
    assert r is not None
    assert r.format == "jacoco"
    assert r.line_pct == 85.0  # report-level LINE 85 covered / 15 missed
    assert r.branch_pct == 80.0  # report-level BRANCH 20 covered / 5 missed


def test_cobertura_line_and_branch():
    r = read_coverage_file(_SAMPLES / "coverage.xml")
    assert r is not None
    assert r.format == "cobertura"
    assert r.line_pct == 72.0
    assert r.branch_pct == 65.0


def test_istanbul_line_and_branch():
    r = read_coverage_file(_SAMPLES / "coverage-summary.json")
    assert r is not None
    assert r.format == "istanbul"
    assert r.line_pct == 91.5
    assert r.branch_pct == 78.3


def test_lcov_line_and_branch():
    # 20 DA lines, 4 with zero hits -> 16/20. 5 BRDA lines, 3 taken -> 3/5.
    r = read_coverage_file(_SAMPLES / "lcov.info")
    assert r is not None
    assert r.format == "lcov"
    assert r.line_pct == 80.0
    assert r.branch_pct == 60.0


def test_unknown_format_returns_none(tmp_path):
    p = tmp_path / ".coverage"
    p.write_bytes(b"SQLite format 3\x00\x01\x02")
    assert read_coverage_file(p) is None


# ---------------------------------------------------------------------------
# 2. Unreadable files: warning, no crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["empty.xml", "truncated-jacoco.xml"])
def test_unreadable_file_returns_none(name):
    assert read_coverage_file(_SAMPLES / name) is None


@pytest.mark.parametrize("name", ["empty.xml", "truncated-jacoco.xml"])
def test_unreadable_file_warns_coverage_unreadable(tmp_path, name):
    f = _copy_sample(name, tmp_path)
    start = time.time()
    _touch(f, start + 1)
    data = read_project_coverage(tmp_path, [name], start, [])
    assert data.results == []
    assert "coverage_unreadable" in data.warnings


# ---------------------------------------------------------------------------
# 3. Freshness
# ---------------------------------------------------------------------------


def test_stale_file_is_ignored_with_warning(tmp_path):
    f = _copy_sample("coverage.xml", tmp_path)
    start = time.time()
    _touch(f, start - 100)
    data = read_project_coverage(tmp_path, ["coverage.xml"], start, [])
    assert data.results == []
    assert "coverage_stale" in data.warnings


def test_file_at_tolerance_edge_is_stale(tmp_path):
    f = _copy_sample("coverage.xml", tmp_path)
    start = 1_000_000.0
    _touch(f, start - 2.0)  # exactly start - tolerance: stale (<=)
    data = read_project_coverage(tmp_path, ["coverage.xml"], start, [])
    assert data.results == []
    assert "coverage_stale" in data.warnings


def test_file_inside_tolerance_is_fresh(tmp_path):
    f = _copy_sample("coverage.xml", tmp_path)
    start = 1_000_000.0
    _touch(f, start - 1.0)  # within the 2 s Windows-resolution window
    data = read_project_coverage(tmp_path, ["coverage.xml"], start, [])
    assert [r.line_pct for r in data.results] == [72.0]
    assert "coverage_stale" not in data.warnings


def test_fresh_file_is_used(tmp_path):
    f = _copy_sample("coverage.xml", tmp_path)
    start = time.time()
    _touch(f, start + 1)
    data = read_project_coverage(tmp_path, ["coverage.xml"], start, [])
    assert len(data.results) == 1
    assert data.results[0].line_pct == 72.0
    assert data.warnings == []


def test_glob_pattern_is_resolved(tmp_path):
    f = _copy_sample("lcov.info", tmp_path, "report.lcov")
    start = time.time()
    _touch(f, start + 1)
    data = read_project_coverage(tmp_path, ["*.lcov"], start, [])
    assert [r.format for r in data.results] == ["lcov"]


def test_binary_dot_coverage_does_not_warn_when_xml_is_read(tmp_path):
    # Python's languages.toml lists both coverage.xml and .coverage.  The
    # .coverage file is a binary database we do not parse; it must not turn a
    # successful read into a coverage_unreadable warning.
    start = time.time()
    _touch(_copy_sample("coverage.xml", tmp_path), start + 1)
    db = tmp_path / ".coverage"
    db.write_bytes(b"SQLite format 3\x00")
    _touch(db, start + 1)
    data = read_project_coverage(tmp_path, ["coverage.xml", ".coverage"], start, [])
    assert [r.line_pct for r in data.results] == [72.0]
    assert data.warnings == []


# ---------------------------------------------------------------------------
# 4. Output fallback and missing
# ---------------------------------------------------------------------------

_PYTEST_COV_OUTPUT = (
    "Name                         Stmts   Miss  Cover\n"
    "----------------------------  ------  ----  -----\n"
    "src/main.py                     100     15    85%\n"
    "TOTAL                           100     15    85%\n"
)


def test_parse_percentage_from_pytest_cov_output():
    assert parse_coverage_from_output(_PYTEST_COV_OUTPUT) == 85.0


def test_parse_percentage_returns_none_without_match():
    assert parse_coverage_from_output("coverage collection finished") is None


def test_output_only_uses_output_percentage(tmp_path):
    data = read_project_coverage(tmp_path, ["coverage.xml"], time.time(), [_PYTEST_COV_OUTPUT])
    assert len(data.results) == 1
    r = data.results[0]
    assert r.line_pct == 85.0
    assert r.branch_pct is None
    assert r.source_file == "<output>"
    assert r.format == "output"
    assert data.warnings == []


def test_no_file_and_no_output_warns_missing(tmp_path):
    data = read_project_coverage(
        tmp_path, ["coverage.xml"], time.time(), ["coverage collection finished"]
    )
    assert data.results == []
    assert data.warnings == ["coverage_missing"]


def test_stale_file_falls_back_to_output(tmp_path):
    start = time.time()
    _touch(_copy_sample("coverage.xml", tmp_path), start - 100)
    data = read_project_coverage(tmp_path, ["coverage.xml"], start, [_PYTEST_COV_OUTPUT])
    assert [r.source_file for r in data.results] == ["<output>"]
    assert "coverage_stale" in data.warnings
    assert "coverage_missing" not in data.warnings


# ---------------------------------------------------------------------------
# 5. Several tools: lowest line coverage, never averaged
# ---------------------------------------------------------------------------


def test_several_tools_keep_separate_results_and_lowest_wins(tmp_path):
    start = time.time()
    _touch(_copy_sample("coverage.xml", tmp_path), start + 1)  # 72.0
    _touch(_copy_sample("jacoco.xml", tmp_path), start + 1)  # 85.0
    data = read_project_coverage(tmp_path, ["coverage.xml", "jacoco.xml"], start, [])
    assert sorted(r.line_pct for r in data.results) == [72.0, 85.0]
    assert data.lowest_line_pct() == 72.0  # not the 78.5 average


def test_lowest_line_pct_is_none_without_results():
    assert CoverageData().lowest_line_pct() is None


def test_lowest_line_pct_picks_minimum():
    data = CoverageData(
        results=[
            CoverageResult(90.0, None, "a", "lcov"),
            CoverageResult(40.0, None, "b", "jacoco"),
            CoverageResult(70.0, None, "c", "istanbul"),
        ]
    )
    assert data.lowest_line_pct() == 40.0


# ---------------------------------------------------------------------------
# 6. Orchestrator wiring (real subprocesses via sys.executable)
# ---------------------------------------------------------------------------


def test_run_project_fresh_coverage_file_is_read(tmp_path):
    proj = _copy_fixture("coverage-fresh", tmp_path)
    result = _run(
        proj, {"coverage": [[sys.executable, "write_coverage.py"]]}, ["coverage.xml"], tmp_path
    )
    stage = _coverage_stage(result)
    assert stage.status == "pass"
    assert stage.coverage_data is not None
    assert [r.line_pct for r in stage.coverage_data.results] == [72.0]
    assert stage.coverage_data.results[0].branch_pct == 65.0
    assert result.warnings == []


def test_run_project_stale_coverage_file_is_ignored(tmp_path):
    proj = _copy_fixture("coverage-stale", tmp_path)
    result = _run(
        proj, {"coverage": [[sys.executable, "make_stale.py"]]}, ["coverage.xml"], tmp_path
    )
    stage = _coverage_stage(result)
    assert stage.status == "pass"  # coverage never fails by itself
    assert stage.coverage_data.results == []
    assert "coverage_stale" in result.warnings


def test_run_project_output_only_coverage(tmp_path):
    proj = _copy_fixture("coverage-output-only", tmp_path)
    code = f"print({_PYTEST_COV_OUTPUT!r})"
    result = _run(proj, {"coverage": [[sys.executable, "-c", code]]}, ["coverage.xml"], tmp_path)
    data = _coverage_stage(result).coverage_data
    assert [(r.line_pct, r.source_file) for r in data.results] == [(85.0, "<output>")]
    assert result.warnings == []


def test_run_project_no_coverage_data_warns_missing(tmp_path):
    proj = _copy_fixture("coverage-none", tmp_path)
    code = "print('coverage collection finished')"
    result = _run(proj, {"coverage": [[sys.executable, "-c", code]]}, ["coverage.xml"], tmp_path)
    data = _coverage_stage(result).coverage_data
    assert data.results == []
    assert "coverage_missing" in result.warnings


def test_run_project_build_gate_skips_coverage_without_data(tmp_path):
    proj = _copy_fixture("coverage-fresh", tmp_path)
    result = _run(
        proj,
        {
            "build": [[sys.executable, "-c", "import sys; sys.exit(1)"]],
            "coverage": [[sys.executable, "write_coverage.py"]],
        },
        ["coverage.xml"],
        tmp_path,
        stages=["build", "coverage"],
    )
    stage = _coverage_stage(result)
    assert stage.status == "skipped"
    assert stage.coverage_data is None
    assert not (proj / "coverage.xml").exists()


# ---------------------------------------------------------------------------
# 7. Report data
# ---------------------------------------------------------------------------


def test_report_data_includes_coverage_only_when_present(tmp_path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    project = _py_project(proj_dir)

    with_cov = ProjectResult(
        project=project,
        stages=[
            StageResult(
                stage="coverage",
                status="pass",
                coverage_data=CoverageData(
                    results=[
                        CoverageResult(72.0, 65.0, str(proj_dir / "coverage.xml"), "cobertura"),
                        CoverageResult(85.0, None, "<output>", "output"),
                    ],
                    warnings=[],
                ),
            )
        ],
    )
    without_cov = ProjectResult(
        project=project,
        stages=[StageResult(stage="coverage", status="skipped", reason="build_gate")],
    )

    data_with, data_without = project_results_to_report_data([with_cov, without_cov], tmp_path)

    assert "coverage" not in data_without
    cov = data_with["coverage"]
    assert cov["lowest_line_pct"] == 72.0
    assert cov["warnings"] == []
    assert [r["source_file"] for r in cov["results"]] == ["proj/coverage.xml", "<output>"]
    assert [r["format"] for r in cov["results"]] == ["cobertura", "output"]
    assert cov["results"][0]["branch_pct"] == 65.0


def test_build_report_passes_coverage_through(tmp_path):
    from pre_llm_checks import build_report

    coverage = {
        "results": [
            {"line_pct": 72.0, "branch_pct": 65.0, "source_file": "coverage.xml", "format": "cobertura"}
        ],
        "lowest_line_pct": 72.0,
        "warnings": [],
    }
    report = build_report(
        [
            {"path": tmp_path, "language": "python", "commands": [], "coverage": coverage},
            {"path": tmp_path, "language": "python", "commands": []},
        ],
        tmp_path,
        50,
    )
    assert report["projects"][0]["coverage"] == coverage
    assert "coverage" not in report["projects"][1]


def test_report_data_keeps_coverage_block_when_data_is_missing(tmp_path):
    pr = ProjectResult(
        project=_py_project(tmp_path),
        stages=[
            StageResult(
                stage="coverage",
                status="pass",
                coverage_data=CoverageData(results=[], warnings=["coverage_missing"]),
            )
        ],
    )
    (entry,) = project_results_to_report_data([pr], tmp_path)
    assert entry["coverage"] == {
        "results": [],
        "lowest_line_pct": None,
        "warnings": ["coverage_missing"],
    }
