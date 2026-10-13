"""Lint gate (Session 23): Lint FAIL or TIMEOUT -> Tests and Coverage SKIP.

Lint WARN (no linter, tool not installed, dependencies missing) or SKIP
changes nothing: tests and coverage run as before.
"""

from __future__ import annotations

import sys
from pathlib import Path

from detection import DetectionResult, StageCommand
from discovery import Project
from orchestrator import OrchestratorOptions, run_project
from output import render_terminal
from pre_llm_checks import load_languages

_PY = load_languages()["python"]


def _cmd(code: str) -> list[str]:
    return [sys.executable, "-c", code]


_OK_TESTS = _cmd("print('2 passed in 0.01s')")
_COV = _cmd("open('coverage-ran.txt', 'w').write('x')")


def _run(tmp_path: Path, lint_cmd, steps=None, timeout_lint=None):
    (tmp_path / "pyproject.toml").write_text("")
    project = Project(path=tmp_path, language="python", primary_build_file="pyproject.toml")
    commands = {
        "tests": [StageCommand(command=_OK_TESTS, source="config")],
        "coverage": [StageCommand(command=_COV, source="config")],
    }
    if lint_cmd:
        commands["lint"] = [StageCommand(command=lint_cmd, source="config")]
    opts = OrchestratorOptions()
    if steps is not None:
        opts.steps = steps
    if timeout_lint is not None:
        opts.timeout_lint = timeout_lint
    return run_project(project=project, lang_cfg=_PY, detection=DetectionResult(commands=commands),
                       opts=opts, log_dir=tmp_path / "logs", repo_root=tmp_path)


def _stage(result, name):
    return next(s for s in result.stages if s.stage == name)


def test_lint_fail_skips_tests_and_coverage(tmp_path):
    result = _run(tmp_path, _cmd("import sys; sys.exit(1)"))
    assert _stage(result, "lint").status == "fail"
    for name in ("tests", "coverage"):
        st = _stage(result, name)
        assert (st.status, st.reason, st.commands) == ("skipped", "lint_failed", [])
    assert not (tmp_path / "coverage-ran.txt").exists()


def test_lint_timeout_skips_tests_and_coverage(tmp_path):
    result = _run(tmp_path, _cmd("import time; time.sleep(30)"), timeout_lint=1.0)
    assert _stage(result, "lint").status == "timeout"
    assert _stage(result, "tests").reason == "lint_failed"
    assert _stage(result, "coverage").reason == "lint_failed"


def test_lint_fail_cells_and_no_detail_lines(tmp_path):
    out = render_terminal([_run(tmp_path, _cmd("import sys; sys.exit(1)"))], tmp_path)
    row = next(line for line in out.splitlines() if line.startswith(". "))
    assert row.split()[-3:] == ["FAIL", "SKIP", "SKIP"]
    assert "tests:" not in out and "coverage:" not in out


def test_no_linter_runs_tests_and_coverage(tmp_path):
    result = _run(tmp_path, None)
    assert _stage(result, "lint").status == "no_linter_configured"
    assert _stage(result, "tests").status == "pass"
    assert _stage(result, "coverage").status == "pass"


def test_lint_tool_missing_runs_tests_and_coverage(tmp_path):
    result = _run(tmp_path, ["pre-llm-no-such-linter-xyz"])
    assert _stage(result, "lint").status == "tool_not_installed"
    assert _stage(result, "tests").status == "pass"
    assert _stage(result, "coverage").status == "pass"


def test_lint_pass_runs_tests_and_coverage(tmp_path):
    result = _run(tmp_path, _cmd("print('ok')"))
    assert _stage(result, "tests").status == "pass"
    assert (tmp_path / "coverage-ran.txt").exists()


def test_steps_without_lint_has_no_gate(tmp_path):
    result = _run(tmp_path, _cmd("import sys; sys.exit(1)"), steps=["tests", "coverage"])
    assert [s.stage for s in result.stages] == ["tests", "coverage"]
    assert _stage(result, "tests").status == "pass"
