"""Tests for C#/.NET detection and coverage paths (Session 15).

- `dotnet build`, `dotnet format --verify-no-changes` (read-only) and `dotnet test`
  are SDK built-ins.  Every command names the primary build file ({build_file}):
  with a .sln and a .csproj in one folder, plain `dotnet format` fails and plain
  `dotnet test` runs no test.
- A .csproj that a .sln / .slnx above it lists is part of the solution's project.
- Coverage is NOT built-in: `--collect:"XPlat Code Coverage"` only works when the
  test project references coverlet.collector, so it runs only when the project
  file declares it or a *.runsettings file sits next to it.
- `dotnet test` writes TestResults/<guid>/coverage.cobertura.xml, so the
  coverage path is a glob (any depth), and stale runs are ignored by mtime.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import read_project_coverage
from detection import detect_commands
from discovery import Project, discover_projects, solution_projects
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
    assert _argv(r, "build") == [["dotnet", "build", "App.csproj"]]
    assert _argv(r, "lint") == [["dotnet", "format", "App.csproj", "--verify-no-changes"]]
    assert _argv(r, "tests") == [["dotnet", "test", "App.csproj"]]
    assert _argv(r, "coverage") == []


def test_sln_is_handled_like_csproj(tmp_path):
    r = detect_commands(_proj(tmp_path, "App.sln", "Microsoft Visual Studio Solution File"), _CS)
    assert _argv(r, "build") == [["dotnet", "build", "App.sln"]]
    assert _argv(r, "coverage") == []


def test_coverlet_package_reference_adds_coverage(tmp_path):
    csproj = '<Project><ItemGroup><PackageReference Include="coverlet.collector" Version="6.0.0" /></ItemGroup></Project>'
    r = detect_commands(_proj(tmp_path, "App.Tests.csproj", csproj), _CS)
    assert _argv(r, "coverage") == [["dotnet", "test", "App.Tests.csproj", "--collect:XPlat Code Coverage"]]
    assert r.commands["coverage"][0].source == "config"


def test_runsettings_file_adds_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, "App.csproj", extra={"coverlet.runsettings": "<RunSettings/>"}), _CS)
    assert _argv(r, "coverage") == [["dotnet", "test", "App.csproj", "--collect:XPlat Code Coverage"]]


def test_unrelated_package_adds_no_coverage(tmp_path):
    csproj = '<Project><ItemGroup><PackageReference Include="xunit" Version="2.5.0" /></ItemGroup></Project>'
    r = detect_commands(_proj(tmp_path, "App.csproj", csproj), _CS)
    assert _argv(r, "coverage") == []


def test_sln_wins_over_csproj_in_discovery(tmp_path):
    (tmp_path / "App.sln").write_text("")
    (tmp_path / "App.csproj").write_text("<Project/>")
    projects = [p for p in discover_projects(tmp_path, _LANGS) if p.language == "csharp"]
    assert [p.primary_build_file for p in projects] == ["App.sln"]


def test_csharp_has_no_dead_stage_names_or_config_files():
    assert "stage_names" not in _CS
    assert "config_files" not in _CS


# --- solution next to a project: every command names the solution -------------------

_CALC_SLN_ENTRY = (
    'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Calc", "Calc.csproj", '
    '"{9ACD7768-F0CE-4857-BA24-333CD7A14387}"\nEndProject\n'
)


def test_sln_next_to_csproj_is_one_project_and_every_command_names_the_sln(tmp_path):
    (tmp_path / "Calc.sln").write_text(_CALC_SLN_ENTRY)
    (tmp_path / "Calc.csproj").write_text("<Project/>")
    projects = [p for p in discover_projects(tmp_path, _LANGS) if p.language == "csharp"]
    assert len(projects) == 1 and projects[0].primary_build_file == "Calc.sln"
    r = detect_commands(projects[0], _CS)
    assert _argv(r, "build") == [["dotnet", "build", "Calc.sln"]]
    assert _argv(r, "lint") == [["dotnet", "format", "Calc.sln", "--verify-no-changes"]]
    assert _argv(r, "tests") == [["dotnet", "test", "Calc.sln"]]


# --- solutions: listed projects are part of the solution ----------------------------


def _sln(*paths: str) -> str:
    lines = ["", "Microsoft Visual Studio Solution File, Format Version 12.00"]
    for i, path in enumerate(paths):
        name = path.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".csproj")
        lines.append(
            f'Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "{name}", "{path}", '
            f'"{{00000000-0000-0000-0000-00000000000{i}}}"'
        )
        lines.append("EndProject")
    return "\n".join(lines) + "\n"


def _write(tmp_path: Path, rel: str, text: str = "<Project/>") -> Path:
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return f


def _csharp(tmp_path: Path) -> list[Project]:
    return [p for p in discover_projects(tmp_path, _LANGS) if p.language == "csharp"]


def test_sln_listed_projects_are_part_of_the_solution(tmp_path):
    _write(tmp_path, "App.sln", _sln("Calc\\Calc.csproj", "Calc.Tests\\Calc.Tests.csproj"))
    _write(tmp_path, "Calc/Calc.csproj")
    _write(tmp_path, "Calc.Tests/Calc.Tests.csproj")
    projects = _csharp(tmp_path)
    assert [(p.path, p.primary_build_file) for p in projects] == [(tmp_path, "App.sln")]


def test_csproj_not_listed_by_the_sln_stays_its_own_project(tmp_path):
    _write(tmp_path, "App.sln", _sln("Calc\\Calc.csproj", "Calc.Tests\\Calc.Tests.csproj"))
    _write(tmp_path, "Calc/Calc.csproj")
    _write(tmp_path, "Calc.Tests/Calc.Tests.csproj")
    _write(tmp_path, "Other/Other.csproj")
    projects = _csharp(tmp_path)
    assert [(p.path, p.primary_build_file) for p in projects] == [
        (tmp_path, "App.sln"),
        (tmp_path / "Other", "Other.csproj"),
    ]


_SLNX = '<Solution><Folder Name="/src/"><Project Path="Calc/Calc.csproj" /></Folder></Solution>'


def test_slnx_listed_project_inside_a_folder_is_part_of_the_solution(tmp_path):
    _write(tmp_path, "App.slnx", _SLNX)
    _write(tmp_path, "Calc/Calc.csproj")
    _write(tmp_path, "Other/Other.csproj")
    projects = _csharp(tmp_path)
    assert [(p.path, p.primary_build_file) for p in projects] == [
        (tmp_path, "App.slnx"),
        (tmp_path / "Other", "Other.csproj"),
    ]


def test_solution_projects_skips_solution_folders(tmp_path):
    folder = (
        'Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "src", "src", '
        '"{11111111-1111-1111-1111-111111111111}"\nEndProject\n'
    )
    sln = _write(tmp_path, "App.sln", folder + _sln("src\\Calc\\Calc.csproj"))
    assert solution_projects(sln) == {(tmp_path / "src" / "Calc" / "Calc.csproj").resolve()}


def test_solution_projects_reads_a_bom(tmp_path):
    sln = tmp_path / "App.sln"
    sln.write_bytes("\ufeff".encode("utf-8") + _sln("Calc\\Calc.csproj").encode("utf-8"))
    assert solution_projects(sln) == {(tmp_path / "Calc" / "Calc.csproj").resolve()}


def test_solution_projects_of_a_missing_file_is_empty(tmp_path):
    assert solution_projects(tmp_path / "Missing.sln") == set()


def test_solution_projects_of_an_invalid_slnx_is_empty(tmp_path):
    assert solution_projects(_write(tmp_path, "App.slnx", "<Solution>")) == set()


def test_sln_whose_test_project_references_coverlet_gets_coverage(tmp_path):
    _write(tmp_path, "App.sln", _sln("Calc\\Calc.csproj", "Calc.Tests\\Calc.Tests.csproj"))
    _write(tmp_path, "Calc/Calc.csproj")
    _write(
        tmp_path,
        "Calc.Tests/Calc.Tests.csproj",
        '<Project><ItemGroup><PackageReference Include="coverlet.collector" Version="6.0.0" />'
        "</ItemGroup></Project>",
    )
    r = detect_commands(Project(path=tmp_path, language="csharp", primary_build_file="App.sln"), _CS)
    assert _argv(r, "coverage") == [["dotnet", "test", "App.sln", "--collect:XPlat Code Coverage"]]


def test_coverlet_only_in_a_comment_of_a_listed_project_adds_no_coverage(tmp_path):
    _write(tmp_path, "App.sln", _sln("Calc.Tests\\Calc.Tests.csproj"))
    _write(
        tmp_path,
        "Calc.Tests/Calc.Tests.csproj",
        '<Project><!-- <PackageReference Include="coverlet.collector" /> --></Project>',
    )
    r = detect_commands(Project(path=tmp_path, language="csharp", primary_build_file="App.sln"), _CS)
    assert _argv(r, "coverage") == []


# --- no-tests and dependency patterns ------------------------------------------------


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def _no_tests(text: str) -> bool:
    return _any(_CS["no_tests_patterns"], text) and not _any(_CS["tests_ran_patterns"], text)


def test_no_test_project_counts_as_no_tests():
    assert _no_tests("  Determining projects to restore...\n  All projects are up-to-date for restore.\n")


def test_test_project_without_tests_counts_as_no_tests():
    assert _no_tests("Starting test execution, please wait...\nNo test is available in /x/Calc.Tests.dll.\n")


def test_passed_line_counts_as_tests_ran():
    text = (
        "Starting test execution, please wait...\n"
        "Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1, "
        "Duration: < 1 ms - Calc.Tests.dll (net8.0)\n"
    )
    assert not _no_tests(text)


def _dep(text: str) -> bool:
    return any(p in text for p in _CS["dep_error_phrases"]) or _any(_CS["dep_error_patterns"], text)


def test_dependency_patterns_match_restore_and_sdk_errors():
    for text in (
        "error NU1301: The local source '/x' doesn't exist.",
        "error NU1101: Unable to find package xunit.",
        "error NETSDK1045: The current .NET SDK does not support targeting .NET 99.0.",
        "Unhandled exception: System.Exception: Restore operation failed.",
    ):
        assert _dep(text), text


def test_dependency_patterns_do_not_match_project_errors():
    for text in ("error NU1605: Detected package downgrade", "error CS1002: ; expected"):
        assert not _dep(text), text


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
