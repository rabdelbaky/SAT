"""Manual output checks for Session 9 (output.py + exit codes + environment block).

Run as:
    python tests/manual_output_check.py

Fixtures are copied to a temp directory, pre_llm_checks.main() is called
directly, and its stdout (the table) and report JSON are inspected.
Prints one PASS/FAIL line per check.  Exit code: 0 if all pass, 1 otherwise.

Also run `python tests/test_output.py`-style comparison by eye if you like:
the exact table format is in tests/fixtures/EXPECTED.md ("terminal-table").
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


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run(name: str, tmp: Path, extra: list[str] | None = None):
    """Run the tool on a copy of fixture *name*; return (exit, stdout, report)."""
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
    return code, out.getvalue(), report


def _sub(tmp: Path, name: str) -> Path:
    d = tmp / name
    d.mkdir()
    return d


def _row(stdout: str, first_cell: str) -> list[str]:
    for line in stdout.splitlines():
        if line.split()[:1] == [first_cell]:
            return line.split()
    return []


def run_checks() -> int:
    os.chdir(_REPO_ROOT)  # keep .pre-llm/logs out of the temp folders
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        n = 0

        # --- build-gate: build fails, rest skipped -------------------------
        code, out, rep = _run("build-gate", tmp)
        n += 1
        _check(n, "build-gate: exit code 1", ok=code == 1, detail=f"got {code}")
        row = _row(out, "build-gate")
        n += 1
        _check(
            n,
            "build-gate: row is FAIL SKIP SKIP SKIP",
            ok=row[-4:] == ["FAIL", "SKIP", "SKIP", "SKIP"],
            detail=f"row={row}\n{out}",
        )
        n += 1
        _check(
            n,
            "build-gate: Details lists 'build-gate / build: FAIL'",
            ok="  build-gate / build: FAIL  " in out,
            detail=out,
        )
        n += 1
        _check(
            n,
            "build-gate: Summary says 1 failed",
            ok="Summary: 1 project: 0 passed, 0 with warnings, 1 failed" in out,
            detail=out,
        )
        env = (rep or {}).get("environment") or {}
        n += 1
        _check(
            n,
            "report has environment.os and a runner with a version (or 'unknown')",
            ok=bool(env.get("os")) and bool(env.get("runners")),
            detail=f"environment={env}",
        )

        # --- no-linter: WARN lint, exit 0 ----------------------------------
        code, out, rep = _run("no-linter", tmp)
        row = _row(out, "no-linter")
        n += 1
        _check(n, "no-linter: exit code 0 (warnings only)", ok=code == 0, detail=f"got {code}")
        n += 1
        _check(
            n,
            "no-linter: Lint cell is WARN, others PASS/%",
            ok=len(row) >= 4 and "WARN" in row,
            detail=f"row={row}\n{out}",
        )
        n += 1
        _check(
            n,
            "no-linter: detail says 'no linter configured'",
            ok="no linter configured" in out,
            detail=out,
        )

        # --- independence: one project fails, other passes ------------------
        code, out, rep = _run("independence", tmp)
        n += 1
        _check(n, "independence: exit code 1", ok=code == 1, detail=f"got {code}")
        n += 1
        _check(
            n,
            "independence: both projects listed, 1 failed in summary",
            ok="proj-pass" in out and "proj-fail" in out and "1 failed" in out,
            detail=out,
        )

        # --- coverage-fresh: coverage cell shows the percentage -------------
        code, out, rep = _run("coverage-fresh", tmp)
        row = _row(out, "coverage-fresh")
        n += 1
        _check(n, "coverage-fresh: Coverage cell is 72.0%", ok=row[-1:] == ["72.0%"], detail=f"row={row}\n{out}")

        # --- stale coverage: not a number -----------------------------------
        code, out, rep = _run("coverage-stale", tmp)
        row = _row(out, "coverage-stale")
        n += 1
        _check(
            n,
            "coverage-stale: Coverage cell is WARN and exit code 0",
            ok=row[-1:] == ["WARN"] and code == 0,
            detail=f"exit={code} row={row}\n{out}",
        )

        # --- verbose shows every command ------------------------------------
        code, out, rep = _run("build-gate", _sub(tmp, "v"), ["--verbose"])
        n += 1
        _check(n, "--verbose prints a 'Commands:' section", ok="Commands:" in out, detail=out)

        # --- dry-run prints no table ----------------------------------------
        code, out, rep = _run("build-gate", _sub(tmp, "d"), ["--dry-run"])
        n += 1
        _check(n, "--dry-run: no results table, exit 0", ok="Summary:" not in out and code == 0, detail=f"exit={code}\n{out}")

    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    total = len(_results)
    print(f"{'All checks passed' if passed == total else 'Some checks FAILED'}: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run_checks())
