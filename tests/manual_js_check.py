"""Manual JavaScript fixture checks for Session 11.

Run as:
    python tests/manual_js_check.py

Each js-* fixture is copied to a temp folder, an empty node_modules is created
in the copy (JavaScript projects are skipped as dependencies_missing without
it), and pre_llm_checks.main() is run.  The table row, exit code and report
are compared with the js-* section of tests/fixtures/EXPECTED.md.  js-detect is
checked with --dry-run (nothing installed or executed).

Needs `node` and `npm` on PATH.  Exit code: 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import contextlib
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
    "js-ok": ("PASS", "PASS", "PASS", "SKIP", 0),
    "js-build-fail": ("FAIL", "SKIP", "SKIP", "SKIP", 1),
    "js-test-fail": ("PASS", "PASS", "FAIL", "SKIP", 1),
    "js-lint-fail": ("PASS", "FAIL", "PASS", "SKIP", 1),
    "js-no-tests": ("PASS", "PASS", "SKIP", "SKIP", 0),
    "js-no-linter": ("PASS", "WARN", "PASS", "SKIP", 0),
}


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run(name: str, tmp: Path, extra: list[str] | None = None, deps: bool = True):
    work = tmp / name
    shutil.copytree(_FIXTURES / name, work)
    if deps:
        (work / "node_modules").mkdir()
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


def _entry(report: dict | None, stage: str) -> dict:
    for cmd in ((report or {}).get("projects") or [{}])[0].get("commands", []):
        if cmd.get("stage") == stage:
            return cmd
    return {}


def run_checks() -> int:
    os.chdir(_REPO_ROOT)
    n = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        reports = {}
        for name, (b, li, t, c, want_exit) in _EXPECTED.items():
            code, out, err, rep = _run(name, tmp)
            reports[name] = rep
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
        e = _entry(reports["js-no-linter"], "lint")
        _check(n, "js-no-linter: lint status is no_linter_configured",
               ok=e.get("status") == "no_linter_configured", detail=f"entry={e}")

        n += 1
        rep = reports["js-build-fail"]
        reasons = [_entry(rep, s).get("reason") for s in ("lint", "tests", "coverage")]
        _check(n, "js-build-fail: lint/tests/coverage skipped with reason build_gate",
               ok=reasons == ["build_gate"] * 3, detail=f"reasons={reasons}")

        n += 1
        e = _entry(reports["js-lint-fail"], "lint")
        tail = " ".join(e.get("output_tail") or [])
        _check(n, "js-lint-fail: lint is fail and output names calc.js",
               ok=e.get("status") == "fail" and "calc.js" in tail, detail=f"entry={e}")

        # --- js-detect: detection only -------------------------------------
        code, out, err, _ = _run("js-detect", tmp, ["--dry-run"], deps=False)
        lines = [ln.strip() for ln in out.splitlines()]
        want = [
            "build: npx --no-install tsc --noEmit  [config]",
            "lint: npx --no-install eslint .  [config]",
            "tests: npx --no-install jest  [config]",
            "coverage: npx --no-install jest --coverage --coverageReporters=json-summary  [config]",
        ]
        n += 1
        _check(n, "js-detect: --dry-run lists tsc, eslint, jest and jest --coverage",
               ok=all(w in lines for w in want) and code == 0, detail=f"exit={code}\n{out}{err}")

    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    total = len(_results)
    print(f"{'All checks passed' if passed == total else 'Some checks FAILED'}: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run_checks())
