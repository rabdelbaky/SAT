"""Manual coverage checks for Session 8 (coverage_readers.py + orchestrator wiring).

Run as:
    python tests/manual_coverage_check.py

Prints one PASS/FAIL line per check.  Fixtures are copied to a temp directory
first (the fixture scripts write/touch coverage.xml in their own folder), then
pre_llm_checks.main() is invoked directly and the written report is inspected.

Exit code: 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import pre_llm_checks  # noqa: E402
from coverage_readers import read_coverage_file  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures"
_SAMPLES = _FIXTURES / "coverage-samples"

_PASS = "PASS"
_FAIL = "FAIL"
_results: list[tuple[int, str, str]] = []


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run_fixture(name: str, tmp: Path) -> tuple[int, dict | None]:
    """Copy fixture *name* to *tmp*, run the tool on the copy, return (exit, report)."""
    work = tmp / name
    shutil.copytree(_FIXTURES / name, work)
    report_path = tmp / f"report_{name}.json"
    try:
        exit_code = pre_llm_checks.main(["--path", str(work), "--output", str(report_path)])
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [internal crash: {exc}]", file=sys.stderr)
        exit_code = 2
    report = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            report = None
    return exit_code, report


def _project(report: dict | None) -> dict:
    try:
        return report["projects"][0]
    except (KeyError, IndexError, TypeError):
        return {}


def _cov_results(report: dict | None) -> list[dict]:
    return (_project(report).get("coverage") or {}).get("results", [])


def _warnings(report: dict | None) -> list[str]:
    return _project(report).get("warnings", [])


def run_checks() -> int:
    os.chdir(_REPO_ROOT)  # keep .pre-llm/logs out of the temp folders

    # ----- Format readers on the sample files -------------------------------
    expected = {
        "jacoco.xml": ("jacoco", 85.0, 80.0),
        "coverage.xml": ("cobertura", 72.0, 65.0),
        "coverage-summary.json": ("istanbul", 91.5, 78.3),
        "lcov.info": ("lcov", 80.0, 60.0),
    }
    n = 0
    for fname, (fmt, line, branch) in expected.items():
        n += 1
        r = read_coverage_file(_SAMPLES / fname)
        got = (r.format, r.line_pct, r.branch_pct) if r else None
        _check(
            n,
            f"{fname}: {fmt} line={line} branch={branch}",
            ok=got == (fmt, line, branch),
            detail=f"got {got}",
        )

    for fname in ("empty.xml", "truncated-jacoco.xml"):
        n += 1
        try:
            r = read_coverage_file(_SAMPLES / fname)
            _check(n, f"{fname}: unreadable returns None, no crash", ok=r is None, detail=f"got {r}")
        except Exception as exc:  # noqa: BLE001
            _check(n, f"{fname}: unreadable returns None, no crash", ok=False, detail=f"raised {exc}")

    # ----- Fixtures through the whole tool ----------------------------------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # coverage-fresh
        code, rep = _run_fixture("coverage-fresh", tmp)
        res = _cov_results(rep)
        n += 1
        _check(
            n,
            "coverage-fresh: fresh coverage.xml is read (line 72.0, branch 65.0)",
            ok=[(r["line_pct"], r["branch_pct"]) for r in res] == [(72.0, 65.0)],
            detail=f"exit={code}, results={res}",
        )
        n += 1
        _check(
            n,
            "coverage-fresh: no coverage warnings",
            ok=not any(w.startswith("coverage_") for w in _warnings(rep)),
            detail=f"warnings={_warnings(rep)}",
        )

        # coverage-stale
        code, rep = _run_fixture("coverage-stale", tmp)
        n += 1
        _check(
            n,
            "coverage-stale: stale coverage.xml is ignored (no results)",
            ok=_cov_results(rep) == [],
            detail=f"results={_cov_results(rep)}",
        )
        n += 1
        _check(
            n,
            "coverage-stale: warning coverage_stale",
            ok="coverage_stale" in _warnings(rep),
            detail=f"warnings={_warnings(rep)}",
        )
        n += 1
        _check(n, "coverage-stale: exit code is 0 (coverage never fails)", ok=code == 0, detail=f"exit={code}")

        # coverage-output-only
        code, rep = _run_fixture("coverage-output-only", tmp)
        res = _cov_results(rep)
        n += 1
        _check(
            n,
            "coverage-output-only: 85.0 parsed from output, source_file <output>",
            ok=[(r["line_pct"], r["source_file"]) for r in res] == [(85.0, "<output>")],
            detail=f"results={res}",
        )

        # coverage-none
        code, rep = _run_fixture("coverage-none", tmp)
        n += 1
        _check(
            n,
            "coverage-none: warning coverage_missing, no results",
            ok="coverage_missing" in _warnings(rep) and _cov_results(rep) == [],
            detail=f"warnings={_warnings(rep)}, results={_cov_results(rep)}",
        )

    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    total = len(_results)
    print(f"{'All checks passed' if passed == total else 'Some checks FAILED'}: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run_checks())
