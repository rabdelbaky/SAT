"""Manual Python fixture checks for Session 10.

Run as:
    python tests/manual_python_check.py

Each python-* fixture is copied to a temp folder and run through
pre_llm_checks.main(); the table row, exit code and report are compared with
the python-* section of tests/fixtures/EXPECTED.md.  python-detect is checked
with --dry-run (nothing is installed or executed).

Needs `python` on PATH (the fixtures' pre-llm.toml files call it).
python-ok and python-test-fail also need `pytest` on PATH: their tests
command is the detected `pytest` (from [tool.pytest.ini_options]).
python-detect-ini is checked with --dry-run only.
python-cov-addopts also needs `pytest-cov` (coverage comes from pytest's own
addopts); python-cov-both is checked with --dry-run only.
python-cov-no-tests and python-cov-test-fail also need pytest and pytest-cov.
Exit code: 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import pre_llm_checks  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures"
_PASS, _FAIL = "PASS", "FAIL"
_results: list[tuple[int, str, str]] = []

# fixture -> (build, lint, tests, coverage, exit code)
_EXPECTED = {
    "python-ok": ("SKIP", "PASS", "PASS", "SKIP", 0),
    "python-test-fail": ("SKIP", "PASS", "FAIL", "SKIP", 1),
    "python-lint-fail": ("SKIP", "FAIL", "PASS", "SKIP", 1),
    "python-no-tests": ("SKIP", "PASS", "SKIP", "SKIP", 0),
    "python-no-linter": ("SKIP", "WARN", "PASS", "SKIP", 0),
    "python-cov-addopts": ("SKIP", "WARN", "PASS", "83.3%", 0),
    "python-cov-no-tests": ("SKIP", "WARN", "SKIP", "FAIL", 1),
    "python-cov-test-fail": ("SKIP", "WARN", "FAIL", "SKIP", 1),
}


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run(name: str, tmp: Path, extra: list[str] | None = None):
    work = tmp / name
    shutil.copytree(_FIXTURES / name, work)
    report_path = tmp / f"report_{name}.json"
    argv = ["--path", str(work), "--output", str(report_path), *(extra or [])]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pre_llm_checks.main(argv)
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None else 0
    report = None
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return code, out.getvalue(), err.getvalue(), report


def _cells(stdout: str) -> list[str]:
    for line in stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["."]:
            return parts[-4:]
    return []


def _stage_entry(report: dict | None, stage: str) -> dict:
    for cmd in ((report or {}).get("projects") or [{}])[0].get("commands", []):
        if cmd.get("stage") == stage:
            return cmd
    return {}


def run_checks() -> int:
    os.chdir(_REPO_ROOT)
    if importlib.util.find_spec("pytest_cov") is None:
        print("FAIL  pytest-cov is not installed: python -m pip install pytest-cov")
        _results.append((0, _FAIL, "pytest-cov is installed"))
    n = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        reports = {}
        outputs = {}
        for name, (b, li, t, c, want_exit) in _EXPECTED.items():
            code, out, err, rep = _run(name, tmp)
            reports[name] = rep
            outputs[name] = out
            n += 1
            _check(
                n,
                f"{name}: table cells {b} {li} {t} {c}",
                ok=_cells(out) == [b, li, t, c],
                detail=f"got {_cells(out)}\n{out}{err}",
            )
            n += 1
            _check(n, f"{name}: exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

        n += 1
        entry = _stage_entry(reports["python-no-linter"], "lint")
        _check(
            n,
            "python-no-linter: report lint status is no_linter_configured",
            ok=entry.get("status") == "no_linter_configured",
            detail=f"entry={entry}",
        )
        n += 1
        entry = _stage_entry(reports["python-lint-fail"], "lint")
        tail = " ".join(entry.get("output_tail") or [])
        _check(
            n,
            "python-lint-fail: lint entry is fail and output names bad_syntax.py",
            ok=entry.get("status") == "fail" and "bad_syntax.py" in tail,
            detail=f"entry={entry}",
        )
        n += 1
        entry = _stage_entry(reports["python-test-fail"], "tests")
        _check(
            n,
            "python-test-fail: tests entry is fail",
            ok=entry.get("status") == "fail",
            detail=f"entry={entry}",
        )
        for name in ("python-ok", "python-test-fail"):
            entry = _stage_entry(reports[name], "tests")
            n += 1
            _check(
                n,
                f"{name}: tests entry is the detected pytest (source config)",
                ok=entry.get("command") == ["pytest"] and entry.get("source") == "config",
                detail=f"entry={entry}",
            )
        n += 1
        _check(
            n,
            "python-no-linter: stdout says 'no linter configured'",
            ok="no linter configured" in outputs["python-no-linter"],
            detail=outputs["python-no-linter"],
        )

        n += 1
        entry = _stage_entry(reports["python-cov-addopts"], "coverage")
        _check(
            n,
            "python-cov-addopts: coverage entry is pytest --cov-report=xml (source config)",
            ok=entry.get("command") == ["pytest", "--cov-report=xml"]
            and entry.get("source") == "config",
            detail=f"entry={entry}",
        )
        n += 1
        cov = ((reports["python-cov-addopts"] or {}).get("projects") or [{}])[0].get(
            "coverage"
        ) or {}
        pct = cov.get("lowest_line_pct")
        _check(
            n,
            "python-cov-addopts: report coverage lowest_line_pct is 83.3",
            ok=isinstance(pct, (int, float)) and round(pct, 1) == 83.3,
            detail=f"coverage={cov}",
        )

        n += 1
        tests = _stage_entry(reports["python-cov-no-tests"], "tests")
        entry = _stage_entry(reports["python-cov-no-tests"], "coverage")
        _check(
            n,
            "python-cov-no-tests: tests skipped (no_tests_found), coverage fail "
            "(no_tests_found), coverage not run",
            ok=tests.get("status") == "skipped"
            and tests.get("reason") == "no_tests_found"
            and entry.get("status") == "fail"
            and entry.get("reason") == "no_tests_found"
            and entry.get("command") is None,
            detail=f"tests={tests} coverage={entry}",
        )
        n += 1
        _check(
            n,
            "python-cov-no-tests: stdout says 'coverage: FAIL  no tests found'",
            ok="coverage: FAIL  no tests found" in outputs["python-cov-no-tests"],
            detail=outputs["python-cov-no-tests"],
        )
        n += 1
        entry = _stage_entry(reports["python-cov-test-fail"], "coverage")
        _check(
            n,
            "python-cov-test-fail: coverage skipped (tests_failed), coverage not run",
            ok=entry.get("status") == "skipped"
            and entry.get("reason") == "tests_failed"
            and entry.get("command") is None,
            detail=f"entry={entry}",
        )

        # --- python-detect: detection only, --dry-run ----------------------
        code, out, err, _ = _run("python-detect", tmp, ["--dry-run"])
        lines = [ln.strip() for ln in out.splitlines()]
        want = [
            "lint: ruff check .  [config]",
            "tests: pytest  [config]",
            "coverage: pytest --cov --cov-report=xml  [config]",
        ]
        n += 1
        _check(
            n,
            "python-detect: --dry-run lists ruff, pytest, pytest --cov from pyproject",
            ok=all(w in lines for w in want) and code == 0,
            detail=f"exit={code}\n{out}{err}",
        )
        n += 1
        _check(
            n,
            "python-detect: no build command is listed for Python",
            ok=not any(ln.startswith("build:") for ln in lines),
            detail=out,
        )

        # --- python-detect-ini: setup.cfg sections, --dry-run ----------------
        code, out, err, _ = _run("python-detect-ini", tmp, ["--dry-run"])
        lines = [ln.strip() for ln in out.splitlines()]
        stage_lines = [
            ln for ln in lines if ln.split(":", 1)[0] in ("build", "lint", "tests", "coverage")
        ]
        want = [
            "lint: flake8 .  [config]",
            "tests: pytest  [config]",
            "coverage: pytest --cov --cov-report=xml  [config]",
        ]
        n += 1
        _check(
            n,
            "python-detect-ini: --dry-run lists exactly flake8, pytest, pytest --cov from setup.cfg",
            ok=stage_lines == want and code == 0,
            detail=f"exit={code} stage_lines={stage_lines}\n{out}{err}",
        )
        n += 1
        _check(
            n,
            "python-detect-ini: no build command is listed",
            ok=not any(ln.startswith("build:") for ln in lines),
            detail=out,
        )

        # --- python-cov-both: addopts --cov plus [tool.coverage], --dry-run ---
        code, out, err, _ = _run("python-cov-both", tmp, ["--dry-run"])
        lines = [ln.strip() for ln in out.splitlines()]
        stage_lines = [
            ln for ln in lines if ln.split(":", 1)[0] in ("build", "lint", "tests", "coverage")
        ]
        want = [
            "tests: pytest  [config]",
            "coverage: pytest --cov-report=xml  [config]",
        ]
        n += 1
        _check(
            n,
            "python-cov-both: --dry-run lists exactly pytest and pytest --cov-report=xml",
            ok=stage_lines == want and code == 0,
            detail=f"exit={code} stage_lines={stage_lines}\n{out}{err}",
        )

    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    total = len(_results)
    print(f"{'All checks passed' if passed == total else 'Some checks FAILED'}: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run_checks())
