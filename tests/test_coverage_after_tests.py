"""Coverage after the tests stage (Session 22).

Tests FAIL or TIMEOUT -> Coverage SKIP (reason tests_failed), not run.
Tests found no tests  -> Coverage FAIL (reason no_tests_found), not run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from detection import DetectionResult, StageCommand
from discovery import Project
from orchestrator import OrchestratorOptions, run_project
from output import render_terminal
from pre_llm_checks import load_languages

_PY = load_languages()["python"]
_COV_MARK = "coverage-ran.txt"


def _print(text: str) -> list[str]:
    return [sys.executable, "-c", f"print({text!r})"]


def _exit(code: int) -> list[str]:
    return [sys.executable, "-c", f"import sys; sys.exit({code})"]


def _cov_cmd() -> list[str]:
    # Writes a marker file, so a test can prove the command never ran.
    return [sys.executable, "-c", f"open({_COV_MARK!r}, 'w').write('x')"]


def _run(tmp_path: Path, tests_cmd: list[str], lang_cfg: dict = _PY, steps=None, timeout_tests=None):
    (tmp_path / "pyproject.toml").write_text("")
    project = Project(path=tmp_path, language="python", primary_build_file="pyproject.toml")
    commands = {"coverage": [StageCommand(command=_cov_cmd(), source="config")]}
    if tests_cmd:
        commands["tests"] = [StageCommand(command=tests_cmd, source="config")]
    opts = OrchestratorOptions()
    if steps is not None:
        opts.steps = steps
    if timeout_tests is not None:
        opts.timeout_tests = timeout_tests
    return run_project(
        project=project,
        lang_cfg=lang_cfg,
        detection=DetectionResult(commands=commands),
        opts=opts,
        log_dir=tmp_path / "logs",
        repo_root=tmp_path,
    )


def _stage(result, name: str):
    return next(s for s in result.stages if s.stage == name)


def test_tests_fail_skips_coverage(tmp_path):
    result = _run(tmp_path, _exit(1))
    cov = _stage(result, "coverage")
    assert _stage(result, "tests").status == "fail"
    assert (cov.status, cov.reason, cov.commands) == ("skipped", "tests_failed", [])
    assert not (tmp_path / _COV_MARK).exists()


def test_tests_timeout_skips_coverage(tmp_path):
    slow = [sys.executable, "-c", "import time; time.sleep(30)"]
    result = _run(tmp_path, slow, timeout_tests=1.0)
    cov = _stage(result, "coverage")
    assert _stage(result, "tests").status == "timeout"
    assert (cov.status, cov.reason) == ("skipped", "tests_failed")
    assert not (tmp_path / _COV_MARK).exists()


def test_tests_fail_coverage_cell_is_skip_with_no_detail(tmp_path):
    out = render_terminal([_run(tmp_path, _exit(1))], tmp_path)
    row = next(line for line in out.splitlines() if line.startswith(". "))
    assert row.split()[-1] == "SKIP"
    assert "coverage:" not in out


def test_pytest_no_tests_is_skip_and_coverage_fails(tmp_path):
    # pytest prints this and exits 5 when it collects nothing.
    no_tests = [sys.executable, "-c",
                "print('collected 0 items'); print('=== no tests ran in 0.01s ==='); "
                "import sys; sys.exit(5)"]
    result = _run(tmp_path, no_tests)
    tests, cov = _stage(result, "tests"), _stage(result, "coverage")
    assert (tests.status, tests.reason) == ("skipped", "no_tests_found")
    assert (cov.status, cov.reason, cov.commands) == ("fail", "no_tests_found", [])
    assert not (tmp_path / _COV_MARK).exists()
    out = render_terminal([result], tmp_path)
    assert ". / coverage: FAIL  no tests found" in out
    assert "tests: FAIL" not in out


def test_unittest_ran_zero_tests_is_skip(tmp_path):
    zero = [sys.executable, "-c",
            "import sys; print('Ran 0 tests in 0.000s', file=sys.stderr); "
            "print('NO TESTS RAN', file=sys.stderr); sys.exit(5)"]
    result = _run(tmp_path, zero)
    assert (_stage(result, "tests").status, _stage(result, "tests").reason) == ("skipped", "no_tests_found")
    assert _stage(result, "coverage").status == "fail"


def test_pytest_real_failure_stays_fail(tmp_path):
    failed = [sys.executable, "-c", "print('1 failed, 2 passed in 0.05s'); import sys; sys.exit(1)"]
    result = _run(tmp_path, failed)
    assert _stage(result, "tests").status == "fail"
    assert _stage(result, "coverage").reason == "tests_failed"


def test_tests_pass_coverage_runs(tmp_path):
    result = _run(tmp_path, _print("2 passed in 0.01s"))
    assert _stage(result, "tests").status == "pass"
    assert _stage(result, "coverage").status == "pass"
    assert (tmp_path / _COV_MARK).exists()


def test_no_test_runner_leaves_coverage_alone(tmp_path):
    # No tests command at all (nothing_to_run) is not "no tests found".
    result = _run(tmp_path, [])
    assert _stage(result, "tests").reason == "nothing_to_run"
    assert _stage(result, "coverage").status == "pass"


def test_coverage_only_steps_still_runs(tmp_path):
    # --steps coverage: there is no tests stage, so nothing gates coverage.
    result = _run(tmp_path, _exit(1), steps=["coverage"])
    assert [s.stage for s in result.stages] == ["coverage"]
    assert _stage(result, "coverage").status == "pass"


def test_python_patterns():
    def no_tests(text: str, kind: str) -> bool:
        hit = any(re.search(p, text, re.MULTILINE) for p in _PY[kind])
        ran = any(re.search(p, text, re.MULTILINE) for p in _PY["tests_ran_patterns"])
        return hit and not ran

    assert no_tests("collected 0 items\n\n==== no tests ran in 0.01s ====", "no_tests_fail_patterns")
    assert no_tests("no tests ran in 1.20s", "no_tests_fail_patterns")
    assert no_tests("Ran 0 tests in 0.000s\n\nNO TESTS RAN", "no_tests_fail_patterns")
    assert no_tests("Ran 0 tests in 0.000s\n\nOK", "no_tests_patterns")
    assert not no_tests("1 failed, 1 passed in 0.03s", "no_tests_fail_patterns")
    assert not no_tests("Ran 3 tests in 0.001s\n\nFAILED (failures=1)", "no_tests_fail_patterns")
