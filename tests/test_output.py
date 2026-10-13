"""Tests for output.py (Session 9): terminal table, summary, environment block;
plus exit codes (orchestrator.compute_exit_code) and report wiring.

Seams under test
----------------
1. render_terminal(results, repo_root, *, verbose=False) -> str
2. cell_text(stage_result) / project_state(project_result)
3. collect_environment(results, version_fn, os_name) -> dict ; probe_version(exe, cwd)
4. compute_exit_code(results, was_interrupted, no_projects)
5. pre_llm_checks.build_report(..., environment=...)

The big table comparison reads its expected text from tests/fixtures/EXPECTED.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import CoverageData, CoverageResult
from discovery import Project
from orchestrator import (
    CommandRecord,
    ProjectResult,
    StageResult,
    compute_exit_code,
)
from output import (
    cell_text,
    collect_environment,
    probe_version,
    project_state,
    render_terminal,
)

_EXPECTED_MD = Path(__file__).parent / "fixtures" / "EXPECTED.md"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _rec(stage, status, command=None, log=None, duration=1.0) -> CommandRecord:
    return CommandRecord(
        command=command or ["tool", stage],
        source="override",
        stage=stage,
        status=status,
        duration_s=duration,
        output_tail=[],
        log_path=log,
    )


def _stage(stage, status="pass", *, reason=None, rec_status=None, command=None, log=None, cov=None):
    commands = []
    if status not in ("skipped", "no_linter_configured"):
        commands = [_rec(stage, rec_status or status, command, log)]
    return StageResult(stage=stage, status=status, reason=reason, commands=commands, coverage_data=cov)


def _project(root, rel, language, tested, stages, warnings=None, interrupted=False):
    path = root / rel if rel != "." else root
    return ProjectResult(
        project=Project(
            path=path, language=language, primary_build_file="x", tested=tested
        ),
        stages=stages,
        warnings=warnings or [],
        interrupted=interrupted,
    )


def _cov(*pcts) -> CoverageData:
    return CoverageData(results=[CoverageResult(p, None, "f", "lcov") for p in pcts])


def _all_pass(root, rel="app", language="python", tested=True):
    return _project(
        root,
        rel,
        language,
        tested,
        [
            _stage("build"),
            _stage("lint"),
            _stage("tests"),
            _stage("coverage", cov=_cov(90.0)),
        ],
    )


def _expected_table_block() -> str:
    text = _EXPECTED_MD.read_text(encoding="utf-8")
    section = text.split("## terminal-table", 1)[1]
    after = section.split("**Expected output:**", 1)[1]
    m = re.search(r"```\n(.*?)\n```", after, re.DOTALL)
    assert m, "no fenced block under 'Expected output' in EXPECTED.md"
    return m.group(1)


# ---------------------------------------------------------------------------
# 1. Cells (worst wins)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage, expected",
    [
        (_stage("tests", "pass"), "PASS"),
        (_stage("tests", "fail"), "FAIL"),
        (_stage("tests", "timeout"), "TIMEOUT"),
        (_stage("tests", "interrupted"), "INTR"),
        (_stage("tests", "skipped", reason="build_gate"), "SKIP"),
        (_stage("lint", "no_linter_configured"), "WARN"),
        (_stage("tests", "dependencies_missing"), "WARN"),
        # runner reports tool_not_installed but the stage status stays "pass"
        (_stage("tests", "pass", rec_status="tool_not_installed"), "WARN"),
    ],
)
def test_cell_text(stage, expected):
    assert cell_text(stage) == expected


def test_cell_worst_wins_across_commands():
    st = StageResult(
        stage="tests",
        status="fail",
        commands=[_rec("tests", "pass"), _rec("tests", "fail")],
    )
    assert cell_text(st) == "FAIL"
    st = StageResult(
        stage="tests",
        status="pass",
        commands=[_rec("tests", "tool_not_installed"), _rec("tests", "pass")],
    )
    assert cell_text(st) == "WARN"


def test_coverage_cell_shows_lowest_line_percentage():
    assert cell_text(_stage("coverage", cov=_cov(85.0, 72.0))) == "72.0%"
    assert cell_text(_stage("coverage", cov=_cov(100.0))) == "100.0%"


def test_coverage_cell_without_data_is_warn():
    assert cell_text(_stage("coverage", cov=CoverageData(warnings=["coverage_missing"]))) == "WARN"


def test_coverage_cell_failed_command_stays_fail_even_with_data():
    assert cell_text(_stage("coverage", "fail", cov=_cov(80.0))) == "FAIL"


# ---------------------------------------------------------------------------
# 2. Table
# ---------------------------------------------------------------------------


def _expected_md_results(root):
    backend = _project(
        root,
        "backend",
        "python",
        False,
        [
            _stage("build"),
            _stage("lint", "no_linter_configured"),
            _stage("tests", "fail", command=["pytest", "-q"], log=".pre-llm/logs/backend/tests-0.log"),
            _stage("coverage", cov=_cov(72.0)),
        ],
    )
    web = _project(
        root,
        "web",
        "javascript",
        True,
        [
            _stage("build", "fail", command=["npm", "run", "build"], log=".pre-llm/logs/web/build-0.log"),
            _stage("lint", "skipped", reason="build_gate"),
            _stage("tests", "skipped", reason="build_gate"),
            _stage("coverage", "skipped", reason="build_gate"),
        ],
    )
    worker = _project(
        root,
        "services/worker",
        "go",
        False,
        [
            _stage("build"),
            _stage("lint"),
            _stage("tests"),
            _stage("coverage", cov=CoverageData(warnings=["coverage_missing"])),
        ],
        warnings=["coverage_missing"],
    )
    return [backend, web, worker]


def test_full_output_matches_expected_md(tmp_path):
    out = render_terminal(_expected_md_results(tmp_path), tmp_path)
    assert out.rstrip("\n") == _expected_table_block()


def test_all_pass_prints_only_table_and_summary(tmp_path):
    out = render_terminal([_all_pass(tmp_path, "app")], tmp_path)
    assert out.splitlines() == [
        "Project  Language  Build  Lint  Tests  Coverage",
        "-------  --------  -----  ----  -----  --------",
        "app      python    PASS   PASS  PASS   90.0%",
        "",
        "Summary: 1 project: 1 passed, 0 with warnings, 0 failed",
    ]


def test_root_project_is_shown_as_dot(tmp_path):
    out = render_terminal([_all_pass(tmp_path, ".")], tmp_path)
    assert out.splitlines()[2].startswith(".  ")


def test_timeout_and_interrupt_get_detail_lines(tmp_path):
    p = _project(
        tmp_path,
        "svc",
        "python",
        True,
        [
            _stage("build"),
            _stage("lint"),
            _stage("tests", "timeout", command=["pytest"], log="l/t.log"),
            _stage("coverage", "interrupted", command=["cov"], log=None),
        ],
        interrupted=True,
    )
    out = render_terminal([p], tmp_path)
    assert "  svc / tests: TIMEOUT  pytest  (log: l/t.log)" in out
    assert "  svc / coverage: INTR  cov" in out
    assert out.rstrip().endswith("Summary: 1 project: 0 passed, 0 with warnings, 1 failed (interrupted)")


def test_detail_log_path_is_relative_to_repo_root(tmp_path):
    absolute_log = str(tmp_path / ".pre-llm" / "logs" / "app" / "tests-0.log")
    p = _project(
        tmp_path,
        "app",
        "python",
        True,
        [_stage("tests", "fail", command=["pytest"], log=absolute_log)],
    )
    out = render_terminal([p], tmp_path)
    assert "(log: .pre-llm/logs/app/tests-0.log)" in out
    assert str(tmp_path) not in out


def test_tool_not_installed_detail_names_the_tool(tmp_path):
    p = _project(
        tmp_path,
        "svc",
        "java",
        False,
        [_stage("build", "pass", rec_status="tool_not_installed", command=["mvn", "package"])],
    )
    out = render_terminal([p], tmp_path)
    assert "  svc / build: WARN  tool not installed: mvn" in out


def test_project_warnings_section(tmp_path):
    p = _all_pass(tmp_path, "app")
    p.warnings = ["dependencies_missing", "gitignore_missing"]
    out = render_terminal([p], tmp_path)
    assert "Warnings:\n  app: dependencies_missing\n  app: gitignore_missing\n" in out
    assert out.rstrip().endswith("1 project: 0 passed, 1 with warnings, 0 failed")


def test_nothing_to_run_project_is_all_skip_with_warning(tmp_path):
    p = _project(
        tmp_path,
        "empty",
        "python",
        True,
        [_stage(s, "skipped", reason="nothing_to_run") for s in ("build", "lint", "tests", "coverage")],
        warnings=["nothing_to_run"],
    )
    out = render_terminal([p], tmp_path)
    assert "empty    python    SKIP   SKIP  SKIP   SKIP" in out
    assert "  empty: nothing_to_run" in out
    assert "Details:" not in out


def test_stage_not_run_is_skip(tmp_path):
    p = _project(tmp_path, "a", "python", True, [_stage("tests")])
    row = render_terminal([p], tmp_path).splitlines()[2]
    assert row.split() == ["a", "python", "SKIP", "SKIP", "PASS", "SKIP"]


def test_verbose_lists_every_command(tmp_path):
    p = _all_pass(tmp_path, "app")
    p.stages[0].commands[0].command = ["python", "-m", "build"]
    p.stages[0].commands[0].duration_s = 1.234
    quiet = render_terminal([p], tmp_path)
    loud = render_terminal([p], tmp_path, verbose=True)
    assert "Commands:" not in quiet
    assert "Commands:\n  app / build: PASS  python -m build  (1.2s)\n" in loud
    assert loud.count("\n  app / ") == 4  # one line per command


def test_summary_pluralises(tmp_path):
    out = render_terminal(
        [_all_pass(tmp_path, "a"), _all_pass(tmp_path, "b")], tmp_path
    )
    assert out.rstrip().endswith("Summary: 2 projects: 2 passed, 0 with warnings, 0 failed")


def test_project_state(tmp_path):
    assert project_state(_all_pass(tmp_path)) == "passed"
    failed = _project(tmp_path, "x", "python", True, [_stage("tests", "fail")])
    assert project_state(failed) == "failed"
    timed = _project(tmp_path, "x", "python", True, [_stage("tests", "timeout")])
    assert project_state(timed) == "failed"
    warn = _project(tmp_path, "x", "python", True, [_stage("lint", "no_linter_configured")])
    assert project_state(warn) == "warnings"
    skip_only = _project(tmp_path, "x", "python", True, [_stage("lint", "skipped")])
    assert project_state(skip_only) == "passed"


def test_empty_results_render_nothing_crashy(tmp_path):
    assert render_terminal([], tmp_path).strip().endswith("Summary: 0 projects: 0 passed, 0 with warnings, 0 failed")


# ---------------------------------------------------------------------------
# 3. Exit codes
# ---------------------------------------------------------------------------


def test_exit_0_when_all_pass(tmp_path):
    assert compute_exit_code([_all_pass(tmp_path)], was_interrupted=False) == 0


def test_exit_0_with_only_warnings(tmp_path):
    p = _project(
        tmp_path,
        "x",
        "python",
        True,
        [
            _stage("lint", "no_linter_configured"),
            _stage("tests", "pass", rec_status="tool_not_installed"),
            _stage("build", "dependencies_missing"),
        ],
        warnings=["nothing_to_run", "coverage_missing"],
    )
    assert compute_exit_code([p], was_interrupted=False) == 0


def test_exit_1_on_fail(tmp_path):
    p = _project(tmp_path, "x", "python", True, [_stage("tests", "fail")])
    assert compute_exit_code([_all_pass(tmp_path), p], was_interrupted=False) == 1


def test_exit_1_on_timeout(tmp_path):
    p = _project(tmp_path, "x", "python", True, [_stage("build", "timeout")])
    assert compute_exit_code([p], was_interrupted=False) == 1


def test_exit_130_wins_over_failures(tmp_path):
    p = _project(tmp_path, "x", "python", True, [_stage("tests", "fail")])
    assert compute_exit_code([p], was_interrupted=True) == 130


def test_exit_3_when_no_projects():
    assert compute_exit_code([], was_interrupted=False, no_projects=True) == 3


# ---------------------------------------------------------------------------
# 4. Environment block
# ---------------------------------------------------------------------------


def _fake_versions(table):
    def fn(exe, cwd):
        return table.get(exe)

    return fn


def test_environment_lists_each_runner_once(tmp_path):
    a = _project(tmp_path, "a", "python", True, [_stage("build", command=["python3", "-m", "build"]), _stage("tests", command=["python3", "-m", "pytest"])])
    b = _project(tmp_path, "b", "javascript", True, [_stage("tests", command=["npm", "test"])])
    env = collect_environment([a, b], _fake_versions({"python3": "Python 3.11.5", "npm": "10.2.0"}), os_name="TestOS 1")
    assert env == {"os": "TestOS 1", "runners": {"python3": "Python 3.11.5", "npm": "10.2.0"}}


def test_environment_unknown_when_version_fails(tmp_path):
    p = _project(tmp_path, "a", "go", True, [_stage("tests", command=["go", "test"])])
    assert collect_environment([p], _fake_versions({}), os_name="x")["runners"] == {"go": "unknown"}


def test_environment_unknown_when_version_fn_raises(tmp_path):
    p = _project(tmp_path, "a", "go", True, [_stage("tests", command=["go", "test"])])

    def boom(exe, cwd):
        raise RuntimeError("nope")

    assert collect_environment([p], boom, os_name="x")["runners"] == {"go": "unknown"}


def test_environment_skips_runners_that_never_ran(tmp_path):
    p = _project(
        tmp_path,
        "a",
        "python",
        True,
        [
            StageResult("build", "skipped", commands=[_rec("build", "skipped", ["mvn", "package"])]),
            _stage("tests", command=["pytest"]),
        ],
    )
    env = collect_environment([p], _fake_versions({"pytest": "pytest 8"}), os_name="x")
    assert env["runners"] == {"pytest": "pytest 8"}


def test_environment_runner_name_strips_path_and_windows_suffix(tmp_path):
    p = _project(
        tmp_path,
        "a",
        "java",
        True,
        [_stage("build", command=["C:\\tools\\mvnw.cmd", "package"]), _stage("tests", command=["/usr/bin/python3.11", "-m", "pytest"])],
    )
    env = collect_environment([p], _fake_versions({}), os_name="x")
    assert sorted(env["runners"]) == ["mvnw", "python3.11"]


def test_environment_never_probes_project_scripts_or_wrappers(tmp_path):
    p = _project(
        tmp_path,
        "a",
        "java",
        True,
        [
            _stage("build", command=["./check.sh", "x"]),
            _stage("lint", command=["scripts\\run.bat"]),
            _stage("tests", command=["gradlew", "build"]),
            _stage("coverage", command=["mvnw.cmd", "verify"]),
        ],
    )
    q = _project(tmp_path, "b", "python", True, [_stage("tests", command=["python", "-c", "pass"])])
    probed: list[str] = []

    def version_fn(exe, cwd):
        probed.append(exe)
        return "v1"

    runners = collect_environment([p, q], version_fn, os_name="x")["runners"]

    assert probed == ["python"]
    assert runners["python"] == "v1"
    others = {name: v for name, v in runners.items() if name != "python"}
    assert others == {
        "check.sh": "unknown",
        "run": "unknown",
        "gradlew": "unknown",
        "mvnw": "unknown",
    }


def test_environment_default_os_name_is_non_empty(tmp_path):
    env = collect_environment([], _fake_versions({}))
    assert isinstance(env["os"], str) and env["os"].strip()
    assert env["runners"] == {}


def test_probe_version_reads_first_line_of_real_executable(tmp_path):
    version = probe_version(sys.executable, tmp_path)
    assert version is not None and version.startswith("Python 3")
    assert "\n" not in version


def test_probe_version_skips_banner_rules_and_jvm_notices(tmp_path, monkeypatch):
    import subprocess

    import output

    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="\n------------------------------------------------------------\nGradle 8.14.3\n",
        stderr="Picked up JAVA_TOOL_OPTIONS: -Dfoo=bar\n",
    )
    monkeypatch.setattr(output.shutil, "which", lambda exe: "/fake/gradle")
    monkeypatch.setattr(output.subprocess, "run", lambda *a, **k: fake)
    assert probe_version("gradle", tmp_path) == "Gradle 8.14.3"

    fake.stdout = ""
    fake.stderr = 'Picked up JAVA_TOOL_OPTIONS: -Dfoo=bar\nopenjdk version "21.0.2"\n'
    assert probe_version("java", tmp_path) == 'openjdk version "21.0.2"'


def test_probe_version_returns_none_for_missing_executable(tmp_path):
    assert probe_version("definitely-not-a-real-tool-xyz", tmp_path) is None


# ---------------------------------------------------------------------------
# 5. Report wiring
# ---------------------------------------------------------------------------


def test_build_report_includes_environment_only_when_given(tmp_path):
    from pre_llm_checks import build_report

    env = {"os": "TestOS 1", "runners": {"python3": "Python 3.11.5"}}
    with_env = build_report([], tmp_path, 50, environment=env)
    without = build_report([], tmp_path, 50)
    assert with_env["environment"] == env
    assert "environment" not in without
