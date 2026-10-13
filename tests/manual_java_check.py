"""Manual Java fixture checks for Session 12.

Run as:
    python tests/manual_java_check.py

Three groups, each compared with the java-* section of tests/fixtures/EXPECTED.md:

1. javac fixtures (java-ok, java-build-fail, java-test-fail, java-lint-fail,
   java-no-linter): a bare pom.xml plus a pre-llm.toml that runs javac/java.
   Need only the JDK.
2. Real Maven and Gradle runs: java-maven-ok, java-gradle-ok and variants of
   them made in a temp copy (build-fail, test-fail, lint-fail, no-tests, see
   _VARIANTS), plus java-maven-multi and java-gradle-multi.  Need `mvn` and
   `gradle` on PATH and internet access the first time (Maven/Gradle download
   the project's plugins and libraries into their own cache; this tool
   installs nothing).  Without `gradle` on PATH, the Gradle checks are shown
   as SKIP (not run) and counted separately; they are never counted as passed.
3. No tools needed: java-maven-wrapper / java-gradle-wrapper (fake mvnw /
   gradlew scripts that only print a line) and java-maven-detect /
   java-gradle-detect (--dry-run).

Every fixture is copied to a temp folder first; the repo is never written.
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
_PASS, _FAIL, _SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[int, str, str]] = []
_WIN = sys.platform == "win32"

# javac fixtures: name -> (build, lint, tests, coverage, exit code)
_EXPECTED_JAVAC = {
    "java-ok": ("PASS", "PASS", "PASS", "SKIP", 0),
    "java-build-fail": ("FAIL", "SKIP", "SKIP", "SKIP", 1),
    "java-test-fail": ("PASS", "PASS", "FAIL", "SKIP", 1),
    "java-lint-fail": ("PASS", "FAIL", "PASS", "SKIP", 1),
    "java-no-linter": ("PASS", "WARN", "PASS", "SKIP", 0),
}

_CALC = "src/main/java/demo/Calc.java"
_CALC_TEST = "src/test/java/demo/CalcTest.java"

# variant -> list of (file, old text, new text); None as file = delete src/test
_VARIANTS = {
    "ok": [],
    "build-fail": [(_CALC, "return a + b;", "return a + ;")],
    "test-fail": [(_CALC_TEST, "assertEquals(5,", "assertEquals(6,")],
    "lint-fail": [
        (_CALC, "    public static int sub", "    // FIXME check overflow\n    public static int sub")
    ],
    "no-tests": [(None, "", "")],
}

# real fixtures: copy name -> (fixture, variant, build, lint, tests, coverage, exit)
_EXPECTED_REAL = {}
for _tool in ("maven", "gradle"):
    _base = f"java-{_tool}-ok"
    _EXPECTED_REAL[f"java-{_tool}-ok"] = (_base, "ok", "PASS", "PASS", "PASS", "33.3%", 0)
    _EXPECTED_REAL[f"java-{_tool}-build-fail"] = (_base, "build-fail", "FAIL", "SKIP", "SKIP", "SKIP", 1)
    _EXPECTED_REAL[f"java-{_tool}-test-fail"] = (_base, "test-fail", "PASS", "PASS", "FAIL", "SKIP", 1)
    _EXPECTED_REAL[f"java-{_tool}-lint-fail"] = (_base, "lint-fail", "PASS", "FAIL", "PASS", "33.3%", 1)
    _EXPECTED_REAL[f"java-{_tool}-no-tests"] = (_base, "no-tests", "PASS", "PASS", "SKIP", "FAIL", 1)
    _EXPECTED_REAL[f"java-{_tool}-multi"] = (f"java-{_tool}-multi", "ok", "PASS", "WARN", "PASS", "SKIP", 0)


def _check(num: int, description: str, *, ok: bool, detail: str = "", skip: str = "") -> None:
    """Record one check.  *skip* (a reason) records SKIP: not run, never a pass."""
    if skip:
        print(f"{_SKIP}  {num:2d}. {description}  (not run: {skip})", flush=True)
        _results.append((num, _SKIP, description))
        return
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}", flush=True)
    _results.append((num, label, description))


def _apply_variant(work: Path, variant: str) -> None:
    for rel, old, new in _VARIANTS[variant]:
        if rel is None:
            shutil.rmtree(work / "src" / "test")
            continue
        path = work / rel
        text = path.read_text(encoding="utf-8")
        assert old in text, f"{old!r} not in {path}"
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _run(name: str, tmp: Path, extra: list[str] | None = None, *, copy_name: str | None = None,
         variant: str = "ok"):
    copy_name = copy_name or name
    work = tmp / copy_name
    shutil.copytree(_FIXTURES / name, work)
    _apply_variant(work, variant)
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


def _rows(stdout: str) -> list[list[str]]:
    """Table rows (split on whitespace) between the dashes line and the first blank line."""
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("-------"):
            rows = []
            for row in lines[i + 1:]:
                if not row.strip():
                    break
                rows.append(row.split())
            return rows
    return []


def _cells(stdout: str) -> list[str]:
    for parts in _rows(stdout):
        if parts[:1] == ["."]:
            return parts[-4:]
    return []


def _entry(report: dict | None, stage: str) -> dict:
    for cmd in ((report or {}).get("projects") or [{}])[0].get("commands", []):
        if cmd.get("stage") == stage:
            return cmd
    return {}


def _tail(entry: dict) -> str:
    return "\n".join(entry.get("output_tail") or [])


def run_checks() -> int:
    os.chdir(_REPO_ROOT)
    n = 0

    # --- tools ---------------------------------------------------------------
    for tool, how in (
        ("javac", "install a JDK 17 or newer"),
        ("mvn", "install Maven and add its bin folder to PATH"),
    ):
        n += 1
        _check(n, f"{tool} is on PATH", ok=shutil.which(tool) is not None,
               detail=f"{how}, open a new PowerShell, run this check again")
    # Gradle is optional here: without it the real Gradle runs are skipped.
    no_gradle = "" if shutil.which("gradle") else "gradle is not on PATH"

    # ignore_cleanup_errors: a Gradle daemon may still hold a file in the copy.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)

        # --- 1. javac fixtures ---------------------------------------------------
        reports = {}
        for name, (b, li, t, c, want_exit) in _EXPECTED_JAVAC.items():
            code, out, err, rep = _run(name, tmp)
            reports[name] = rep
            n += 1
            _check(n, f"{name}: table cells {b} {li} {t} {c}",
                   ok=_cells(out) == [b, li, t, c], detail=f"got {_cells(out)}\n{out}{err}")
            n += 1
            _check(n, f"{name}: exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

        n += 1
        e = _entry(reports["java-no-linter"], "lint")
        _check(n, "java-no-linter: lint status is no_linter_configured",
               ok=e.get("status") == "no_linter_configured", detail=f"entry={e}")

        n += 1
        rep = reports["java-build-fail"]
        reasons = [_entry(rep, s).get("reason") for s in ("lint", "tests", "coverage")]
        _check(n, "java-build-fail: lint/tests/coverage skipped with reason build_gate",
               ok=reasons == ["build_gate"] * 3, detail=f"reasons={reasons}")

        n += 1
        e = _entry(reports["java-lint-fail"], "lint")
        _check(n, "java-lint-fail: lint is fail and output names Calc.java",
               ok=e.get("status") == "fail" and "Calc.java" in _tail(e), detail=f"entry={e}")

        # --- 2. real Maven / Gradle runs -------------------------------------------
        for copy_name, (fixture, variant, b, li, t, c, want_exit) in _EXPECTED_REAL.items():
            skip = no_gradle if "gradle" in copy_name else ""
            if skip:
                n += 1
                _check(n, f"{copy_name}: one table row, cells {b} {li} {t} {c}", ok=False, skip=skip)
                n += 1
                _check(n, f"{copy_name}: exit code {want_exit}", ok=False, skip=skip)
                continue
            print(f"      running {copy_name} (real {'Maven' if 'maven' in copy_name else 'Gradle'}) ...",
                  flush=True)
            code, out, err, rep = _run(fixture, tmp, copy_name=copy_name, variant=variant)
            reports[copy_name] = rep
            n += 1
            _check(n, f"{copy_name}: one table row, cells {b} {li} {t} {c}",
                   ok=len(_rows(out)) == 1 and _cells(out) == [b, li, t, c],
                   detail=f"got {_rows(out)}\n{out}{err}")
            n += 1
            _check(n, f"{copy_name}: exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

        for tool, build_cmd in (("maven", ["mvn", "compile"]), ("gradle", ["gradle", "assemble"])):
            skip = no_gradle if tool == "gradle" else ""
            rep = reports.get(f"java-{tool}-ok")
            n += 1
            e = _entry(rep, "build")
            _check(n, f"java-{tool}-ok: build command is {' '.join(build_cmd)}",
                   ok=e.get("command") == build_cmd and e.get("status") == "pass", detail=f"entry={e}", skip=skip)
            n += 1
            cov = ((rep or {}).get("projects") or [{}])[0].get("coverage") or {}
            files = [r.get("source_file", "") for r in cov.get("results", [])]
            _check(n, f"java-{tool}-ok: coverage read from the JaCoCo XML",
                   ok=any(f.endswith(".xml") and "jacoco" in f.lower() for f in files),
                   detail=f"coverage={cov}", skip=skip)

            rep = reports.get(f"java-{tool}-build-fail")
            n += 1
            e = _entry(rep, "build")
            _check(n, f"java-{tool}-build-fail: build is fail (not dependencies_missing), lint/tests skipped by build_gate",
                   ok=e.get("status") == "fail"
                   and [_entry(rep, s).get("reason") for s in ("lint", "tests")] == ["build_gate"] * 2,
                   detail=f"entry={e}", skip=skip)

            rep = reports.get(f"java-{tool}-test-fail")
            n += 1
            _check(n, f"java-{tool}-test-fail: build passed, tests is fail and names CalcTest",
                   ok=_entry(rep, "build").get("status") == "pass"
                   and _entry(rep, "tests").get("status") == "fail"
                   and "CalcTest" in _tail(_entry(rep, "tests")),
                   detail=f"tests={_entry(rep, 'tests')}", skip=skip)

            rep = reports.get(f"java-{tool}-lint-fail")
            n += 1
            e = _entry(rep, "lint")
            _check(n, f"java-{tool}-lint-fail: lint is fail and output names Calc.java",
                   ok=e.get("status") == "fail" and "Calc.java" in _tail(e), detail=f"entry={e}", skip=skip)

            rep = reports.get(f"java-{tool}-no-tests")
            n += 1
            e = _entry(rep, "tests")
            _check(n, f"java-{tool}-no-tests: tests skipped with reason no_tests_found",
                   ok=e.get("status") == "skipped" and e.get("reason") == "no_tests_found",
                   detail=f"entry={e}", skip=skip)

            rep = reports.get(f"java-{tool}-multi")
            n += 1
            projects = (rep or {}).get("projects") or []
            _check(n, f"java-{tool}-multi: report has one project (modules are part of the root)",
                   ok=len(projects) == 1 and _entry(rep, "tests").get("status") == "pass",
                   detail=f"projects={[p.get('path') for p in projects]}", skip=skip)

        # --- 3. wrappers (fake scripts, no tools needed) ---------------------------
        wrappers = {
            "java-maven-wrapper": (["mvn", "compile"], "mvnw.cmd" if _WIN else "mvnw",
                                   "fixture mvnw.cmd compile" if _WIN else "fixture mvnw (sh) compile"),
            "java-gradle-wrapper": (["gradle", "assemble"], "gradlew.bat" if _WIN else "gradlew",
                                    "fixture gradlew.bat assemble" if _WIN else "fixture gradlew (sh) assemble"),
        }
        for name, (detected, wrapper, marker) in wrappers.items():
            code, out, err, rep = _run(name, tmp)
            n += 1
            _check(n, f"{name}: table cells PASS WARN PASS SKIP, exit 0",
                   ok=_cells(out) == ["PASS", "WARN", "PASS", "SKIP"] and code == 0,
                   detail=f"exit={code} got {_cells(out)}\n{out}{err}")
            e = _entry(rep, "build")
            n += 1
            _check(n, f"{name}: build ran {wrapper} (output has '{marker}')",
                   ok=e.get("command") == [wrapper, detected[1]] and marker in _tail(e),
                   detail=f"entry={e}")
            runners = ((rep or {}).get("environment") or {}).get("runners", {})
            n += 1
            _check(n, f"{name}: environment does not claim the {detected[0]} on PATH ran",
                   # the environment key drops .cmd/.bat: "mvnw.cmd" -> "mvnw"
                   ok=detected[0] not in runners and runners.get(wrapper.split(".")[0]) == "unknown",
                   detail=f"runners={runners}")

        # --- detection-only fixtures: --dry-run --------------------------------------
        detect = {
            "java-maven-detect": [
                "build: mvn compile  [builtin]",
                "lint: mvn checkstyle:check  [config]",
                "tests: mvn test  [builtin]",
                "coverage: mvn jacoco:report  [config]",
            ],
            "java-gradle-detect": [
                "build: gradle assemble  [builtin]",
                "lint: gradle checkstyleMain  [config]",
                "tests: gradle test  [builtin]",
                "coverage: gradle jacocoTestReport  [config]",
            ],
        }
        for name, want in detect.items():
            code, out, err, _ = _run(name, tmp, ["--dry-run"])
            lines = [ln.strip() for ln in out.splitlines()]
            got = [ln for ln in lines if ln.split(":")[0] in ("build", "lint", "tests", "coverage")]
            n += 1
            _check(n, f"{name}: --dry-run lists exactly the expected stage commands",
                   ok=got == want and code == 0, detail=f"exit={code}\n{out}{err}")

    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    skipped = sum(1 for _, label, _ in _results if label == _SKIP)
    total = len(_results) - skipped
    note = f" ({skipped} Gradle checks not run: gradle is not on PATH)" if skipped else ""
    print(f"{'All checks passed' if passed == total else 'Some checks FAILED'}: {passed}/{total}{note}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run_checks())
