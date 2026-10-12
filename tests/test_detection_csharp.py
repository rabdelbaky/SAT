"""Tests for C#/.NET detection and coverage paths (Session 15).

- `dotnet build`, `dotnet format --verify-no-changes` (read-only) and `dotnet test`
  are SDK built-ins.
- Coverage is NOT built-in: `--collect:"XPlat Code Coverage"` only works when the
  test project references coverlet.collector, so it runs only when the project
  file declares it or a *.runsettings file sits next to it.
- `dotnet test` writes TestResults/<guid>/coverage.cobertura.xml, so the
  coverage path is a glob (any depth), and stale runs are ignored by mtime.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import read_project_coverage
from detection import detect_commands
from discovery import Project, discover_projects
from pre_llm_checks import load_languages

_LANGS = load_languages()
_CS = _LANGS["csharp"]

_COBERTURA = '<?xml version="1.0"?><coverage line-rate="0.8" branch-rate="0.5"><packages/></coverage>'


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def _proj(tmp_path: Path, build_file: str, content: str = "<Project/>", extra: dict[str, str] | None = None) -> Project:
    (tmp_path / build_file).write_text(content)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="csharp", primary_build_file=build_file)


def test_bare_csproj_gets_sdk_builtins_and_no_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, "App.csproj"), _CS)
    assert _argv(r, "build") == [["dotnet", "build"]]
    assert _argv(r, "lint") == [["dotnet", "format", "--verify-no-changes"]]
    assert _argv(r, "tests") == [["dotnet", "test"]]
    assert _argv(r, "coverage") == []


def test_sln_is_handled_like_csproj(tmp_path):
    r = detect_commands(_proj(tmp_path, "App.sln", "Microsoft Visual Studio Solution File"), _CS)
    assert _argv(r, "build") == [["dotnet", "build"]]
    assert _argv(r, "coverage") == []


def test_coverlet_package_reference_adds_coverage(tmp_path):
    csproj = '<Project><ItemGroup><PackageReference Include="coverlet.collector" Version="6.0.0" /></ItemGroup></Project>'
    r = detect_commands(_proj(tmp_path, "App.Tests.csproj", csproj), _CS)
    assert _argv(r, "coverage") == [["dotnet", "test", "--collect:XPlat Code Coverage"]]
    assert r.commands["coverage"][0].source == "config"


def test_runsettings_file_adds_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, "App.csproj", extra={"coverlet.runsettings": "<RunSettings/>"}), _CS)
    assert _argv(r, "coverage") == [["dotnet", "test", "--collect:XPlat Code Coverage"]]


def test_unrelated_package_adds_no_coverage(tmp_path):
    csproj = '<Project><ItemGroup><PackageReference Include="xunit" Version="2.5.0" /></ItemGroup></Project>'
    r = detect_commands(_proj(tmp_path, "App.csproj", csproj), _CS)
    assert _argv(r, "coverage") == []


def test_sln_wins_over_csproj_in_discovery(tmp_path):
    (tmp_path / "App.sln").write_text("")
    (tmp_path / "App.csproj").write_text("<Project/>")
    projects = [p for p in discover_projects(tmp_path, _LANGS) if p.language == "csharp"]
    assert [p.primary_build_file for p in projects] == ["App.sln"]


# --- coverage file location -------------------------------------------------------


def _cov_files() -> list[str]:
    return _CS["coverage_files"]


def test_testresults_guid_folder_at_project_root_is_found(tmp_path):
    f = tmp_path / "TestResults" / "3f2a-guid" / "coverage.cobertura.xml"
    f.parent.mkdir(parents=True)
    f.write_text(_COBERTURA)
    start = time.time()
    os.utime(f, (start + 1, start + 1))
    data = read_project_coverage(tmp_path, _cov_files(), start, [])
    assert [(r.format, r.line_pct, r.branch_pct) for r in data.results] == [("cobertura", 80.0, 50.0)]
    assert data.warnings == []


def test_testresults_inside_a_test_project_folder_is_found(tmp_path):
    f = tmp_path / "tests" / "App.Tests" / "TestResults" / "abc" / "coverage.cobertura.xml"
    f.parent.mkdir(parents=True)
    f.write_text(_COBERTURA)
    start = time.time()
    os.utime(f, (start + 1, start + 1))
    data = read_project_coverage(tmp_path, _cov_files(), start, [])
    assert len(data.results) == 1


def test_old_run_folder_is_stale_and_new_one_is_used(tmp_path):
    start = time.time()
    old = tmp_path / "TestResults" / "old" / "coverage.cobertura.xml"
    new = tmp_path / "TestResults" / "new" / "coverage.cobertura.xml"
    for f in (old, new):
        f.parent.mkdir(parents=True)
        f.write_text(_COBERTURA)
    os.utime(old, (start - 3600, start - 3600))
    os.utime(new, (start + 1, start + 1))
    data = read_project_coverage(tmp_path, _cov_files(), start, [])
    assert len(data.results) == 1
    assert "coverage_stale" in data.warnings
