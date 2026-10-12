"""Manual JavaScript fixture checks for Session 11.

Run as:
    python tests/manual_js_check.py

Each js-* / ts-* fixture is copied to a temp folder and pre_llm_checks.main()
is run.  The fixtures declare no packages, so the node_modules check does not
apply and no node_modules folder is needed.  js-missing-deps (which declares
left-pad) is run twice: once as is, and once with an empty node_modules (a
half-done install).  The table row, exit code and report are compared with the
js-* section of tests/fixtures/EXPECTED.md.  js-detect is checked with
--dry-run (nothing installed or executed).

Needs `node`, `npm` and `tsc` (npm install -g typescript) on PATH.
Exit code: 0 if all checks pass, 1 otherwise.
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
    "js-bad-require": ("PASS", "PASS", "FAIL", "SKIP", 1),
    "js-missing-deps": ("SKIP", "SKIP", "SKIP", "SKIP", 0),
    "ts-ok": ("PASS", "WARN", "SKIP", "SKIP", 0),
    "ts-build-fail": ("FAIL", "SKIP", "SKIP", "SKIP", 1),
}


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run(
    name: str,
    tmp: Path,
    extra: list[str] | None = None,
    deps: bool = False,
    copy_name: str | None = None,
):
    copy_name = copy_name or name
    work = tmp / copy_name
    shutil.copytree(_FIXTURES / name, work)
    if deps:
        (work / "node_modules").mkdir()
    report_path = tmp / f"report_{copy_name}.json"
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
        n += 1
        _check(
            n,
            "tsc is on PATH (needed by ts-ok and ts-build-fail)",
            ok=shutil.which("tsc") is not None,
            detail="run: npm install -g typescript   then run this check again",
        )

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

        n += 1
        e = _entry(reports["js-bad-require"], "tests")
        tail = " ".join(e.get("output_tail") or [])
        _check(n, "js-bad-require: tests is fail (code bug) and output names calcx",
               ok=e.get("status") == "fail" and "calcx" in tail, detail=f"entry={e}")

        n += 1
        rep = reports["js-missing-deps"]
        reasons = [_entry(rep, s).get("reason") or "" for s in ("build", "lint", "tests", "coverage")]
        warnings = ((rep or {}).get("projects") or [{}])[0].get("warnings") or []
        _check(n, "js-missing-deps: every stage skipped as dependencies_missing, project warning set",
               ok=all(r.startswith("dependencies_missing") for r in reasons)
               and "dependencies_missing" in warnings,
               detail=f"reasons={reasons} warnings={warnings}")

        # --- js-missing-deps with an empty node_modules (half-done install) --
        code, out, err, rep = _run("js-missing-deps", tmp, deps=True, copy_name="js-missing-deps-nm")
        n += 1
        _check(n, "js-missing-deps + empty node_modules: table cells PASS WARN WARN SKIP",
               ok=_cells(out) == ["PASS", "WARN", "WARN", "SKIP"],
               detail=f"got {_cells(out)}\n{out}{err}")
        n += 1
        _check(n, "js-missing-deps + empty node_modules: exit code 0", ok=code == 0, detail=f"got {code}")
        n += 1
        e = _entry(rep, "tests")
        tail = " ".join(e.get("output_tail") or [])
        _check(n, "js-missing-deps + empty node_modules: tests is dependencies_missing naming left-pad",
               ok=e.get("status") == "dependencies_missing" and "left-pad" in tail, detail=f"entry={e}")

        n += 1
        e = _entry(reports["ts-ok"], "build")
        _check(n, "ts-ok: build is the detected tsc --noEmit (source config) and passes",
               ok=e.get("command") == ["npx", "--no-install", "tsc", "--noEmit"]
               and e.get("source") == "config" and e.get("status") == "pass",
               detail=f"entry={e}")

        n += 1
        e = _entry(reports["ts-build-fail"], "build")
        tail = " ".join(e.get("output_tail") or [])
        _check(n, "ts-build-fail: build is fail with TS2322",
               ok=e.get("status") == "fail" and "TS2322" in tail, detail=f"entry={e}")

        # --- js-detect: detection only -------------------------------------
        code, out, err, _ = _run("js-detect", tmp, ["--dry-run"])
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
