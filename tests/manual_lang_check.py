"""Manual per-language fixture checks (Sessions 13+).

Run as:
    python tests/manual_lang_check.py            # every language
    python tests/manual_lang_check.py go rust    # only these

For each language: execution fixtures are copied to a temp folder, run through
pre_llm_checks.main(), and compared with the table cells and exit code in
tests/fixtures/EXPECTED.md; detect fixtures are checked with --dry-run (nothing
is installed or executed).  A language whose toolchain is not on PATH is
reported as SKIP (not run) for its execution fixtures; a SKIP is never counted
as passed.  Detect fixtures never need the toolchain.

Kotlin (see _kotlin_checks) runs real Gradle, like tests/manual_java_check.py:
kotlin-gradle-ok and variants of it made in a temp copy (build-fail, test-fail,
lint-fail, no-tests, no-linter, see _KOTLIN_VARIANTS), plus kotlin-gradle-multi.
Needs `gradle` on PATH, a JDK, and internet access the first time (Gradle
downloads the Kotlin, detekt and JaCoCo plugins into its own cache; this tool
installs nothing).  Without `gradle` on PATH those checks are shown as SKIP.
kotlin-gradle-wrapper (fake gradlew scripts) and kotlin-detect (--dry-run)
need no Gradle.

Go (see _go_checks) runs real `go` (and `golangci-lint` 2.x for the go-golangci-*
fixtures); without them on PATH those checks are shown as SKIP.  go-missing-deps
runs with GOPROXY=off and an empty module cache, so it needs no internet.

C# (see _csharp_checks) runs real `dotnet` (.NET 8 SDK) and needs internet access
to nuget.org the first time (xunit and coverlet are downloaded once into the NuGet
cache; this tool installs nothing).  Without `dotnet` on PATH those checks are
shown as SKIP.  csharp-missing-deps runs with an empty NUGET_PACKAGES folder and
a RestoreSources folder that does not exist, so it needs no internet.

Rust (see _rust_checks) runs real `cargo` (with the clippy component); without it
on PATH those checks are shown as SKIP.  rust-tarpaulin checks a coverage
percentage when `cargo-tarpaulin` is on PATH, else the dependencies_missing
warning; it is never SKIP when cargo is present.  rust-missing-deps runs with
CARGO_NET_OFFLINE=true and an empty CARGO_HOME, so it needs no internet.

PHP (see _php_checks) runs real `php` (8.2+) and `composer`.  The php-unit-*
fixtures need PHPUnit and PHP_CodeSniffer: the check itself runs `composer install`
once in a temp copy of php-unit-ok (internet needed the first time; this tool
installs nothing) and copies that vendor/ into each php-unit run.  Coverage is a
percentage read from clover.xml when PCOV or Xdebug (coverage mode) is loaded,
else the dependencies_missing warning.  php-unit-missing-deps needs nothing;
php-scripts and php-fixer-script need php and composer; the pre-llm.toml
override fixtures (php-ok, php-test-fail, ...) need only php.  Without them on
PATH those checks are shown as SKIP.

Every fixture is copied to a temp folder first; the repo is never written.
Exit code: 0 if no check FAILED, 1 otherwise.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import pre_llm_checks  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures"
_STAGES = ("build", "lint", "tests", "coverage")
_WIN = sys.platform == "win32"


@dataclass
class Lang:
    tools: list[str] = field(default_factory=list)  # must all be on PATH for execution fixtures
    # fixture -> (build, lint, tests, coverage, exit code)
    execution: dict[str, tuple[str, str, str, str, int]] = field(default_factory=dict)
    # fixture -> expected dry-run stage lines
    detect: dict[str, list[str]] = field(default_factory=dict)
    prepare: Optional[Callable[[Path], None]] = None  # e.g. create vendor/ in the copy
    custom: Optional[Callable[[Path], None]] = None  # language-specific checks, given the temp folder


_counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
_skip_notes: dict[str, int] = {}  # "<what> checks not run: <reason>" -> count
_n = 0


def _report(label: str, text: str, detail: str = "") -> None:
    global _n
    _n += 1
    _counts[label] += 1
    suffix = f"  ({detail})" if detail and label == "FAIL" else ""
    print(f"{label}  {_n:2d}. {text}{suffix}", flush=True)


def _check(text: str, *, ok: bool, detail: str = "", skip: str = "", what: str = "") -> None:
    """Record one check.  *skip* (a reason) records SKIP: not run, never a pass."""
    global _n
    if skip:
        _n += 1
        _counts["SKIP"] += 1
        key = f"{what + ' ' if what else ''}checks not run: {skip}"
        _skip_notes[key] = _skip_notes.get(key, 0) + 1
        print(f"SKIP  {_n:2d}. {text}  (not run: {skip})", flush=True)
        return
    _report("PASS" if ok else "FAIL", text, detail)


def _apply_edits(work: Path, edits) -> None:
    """Apply (file, old text, new text) edits; None as file deletes src/test."""
    for rel, old, new in edits or []:
        if rel is None:
            shutil.rmtree(work / "src" / "test")
            continue
        path = work / rel
        text = path.read_text(encoding="utf-8")
        assert old in text, f"{old!r} not in {path}"
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _run(name: str, tmp: Path, extra: list[str] | None = None, prepare=None, *,
         copy_name: str | None = None, edits=None):
    copy_name = copy_name or name
    work = tmp / copy_name
    shutil.copytree(_FIXTURES / name, work)
    _apply_edits(work, edits)
    if prepare:
        prepare(work)
    report_path = tmp / f"report_{copy_name}.json"
    argv = ["--path", str(work), "--output", str(report_path), *(extra or [])]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pre_llm_checks.main(argv)
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None else 0
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
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


_PCT = "<percent>"  # expected cell: any coverage percentage


def _cells_match(got: list[str], want: list[str]) -> bool:
    return len(got) == len(want) and all(
        (g.endswith("%") and len(g) > 1) if w == _PCT else g == w for g, w in zip(got, want)
    )


def _entry(report: dict | None, stage: str) -> dict:
    for cmd in ((report or {}).get("projects") or [{}])[0].get("commands", []):
        if cmd.get("stage") == stage:
            return cmd
    return {}


def _tail(entry: dict) -> str:
    return "\n".join(entry.get("output_tail") or [])


# ---------------------------------------------------------------------------
# Kotlin: real Gradle runs
# ---------------------------------------------------------------------------

_KT_CALC = "src/main/kotlin/demo/Calc.kt"
_KT_TEST = "src/test/kotlin/demo/CalcTest.kt"
_KT_BUILD = "build.gradle.kts"

# variant -> list of (file, old text, new text); None as file = delete src/test
_KOTLIN_VARIANTS = {
    "ok": [],
    "build-fail": [(_KT_CALC, "a + b", "a +")],
    "test-fail": [(_KT_TEST, "assertEquals(5,", "assertEquals(6,")],
    # detekt's default ForbiddenComment rule flags "FIXME:".
    "lint-fail": [(_KT_CALC, "    fun sub", "    // FIXME: check overflow\n    fun sub")],
    "no-tests": [(None, "", "")],
    "no-linter": [(_KT_BUILD, '    id("io.gitlab.arturbosch.detekt") version "1.23.8"\n', "")],
}

# copy name -> (fixture, variant, build, lint, tests, coverage, exit)
_KOTLIN_REAL = {
    f"kotlin-gradle-{v}": ("kotlin-gradle-ok", v, *cells)
    for v, cells in (
        ("ok", ("PASS", "PASS", "PASS", _PCT, 0)),
        ("build-fail", ("FAIL", "SKIP", "SKIP", "SKIP", 1)),
        ("test-fail", ("PASS", "PASS", "FAIL", _PCT, 1)),
        ("lint-fail", ("PASS", "FAIL", "PASS", _PCT, 1)),
        ("no-tests", ("PASS", "PASS", "SKIP", "WARN", 0)),
        ("no-linter", ("PASS", "WARN", "PASS", _PCT, 0)),
    )
}
_KOTLIN_REAL["kotlin-gradle-multi"] = ("kotlin-gradle-multi", "ok", "PASS", "WARN", "PASS", "SKIP", 0)


def _kotlin_checks(tmp: Path) -> None:
    no_gradle = "" if shutil.which("gradle") else "gradle is not on PATH"

    def check(text: str, *, ok: bool = False, detail: str = "", real: bool = True) -> None:
        _check(text, ok=ok, detail=detail, skip=no_gradle if real else "", what="Gradle")

    reports: dict[str, dict | None] = {}
    for copy_name, (fixture, variant, b, li, t, c, want_exit) in _KOTLIN_REAL.items():
        want = [b, li, t, c]
        if no_gradle:
            check(f"{copy_name}: one table row, cells {' '.join(want)}")
            check(f"{copy_name}: exit code {want_exit}")
            continue
        print(f"      running {copy_name} (real Gradle) ...", flush=True)
        code, out, err, rep = _run(fixture, tmp, copy_name=copy_name, edits=_KOTLIN_VARIANTS[variant])
        reports[copy_name] = rep
        check(f"{copy_name}: one table row, cells {' '.join(want)}",
              ok=len(_rows(out)) == 1 and _cells_match(_cells(out), want),
              detail=f"got {_rows(out)}\n{out}{err}")
        check(f"{copy_name}: exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

    rep = reports.get("kotlin-gradle-ok")
    e = _entry(rep, "build")
    check("kotlin-gradle-ok: build command is gradle assemble",
          ok=e.get("command") == ["gradle", "assemble"] and e.get("status") == "pass", detail=f"entry={e}")
    cov = ((rep or {}).get("projects") or [{}])[0].get("coverage") or {}
    files = [r.get("source_file", "") for r in cov.get("results", [])]
    check("kotlin-gradle-ok: coverage read from the JaCoCo XML",
          ok=any(f.replace("\\", "/").endswith("jacoco/test/jacocoTestReport.xml") for f in files),
          detail=f"coverage={cov}")

    rep = reports.get("kotlin-gradle-build-fail")
    e = _entry(rep, "build")
    reasons = [_entry(rep, s).get("reason") for s in ("lint", "tests")]
    check("kotlin-gradle-build-fail: build is fail (not dependencies_missing), lint/tests skipped by build_gate",
          ok=e.get("status") == "fail" and reasons == ["build_gate"] * 2,
          detail=f"entry={e} reasons={reasons}")

    rep = reports.get("kotlin-gradle-test-fail")
    e = _entry(rep, "tests")
    check("kotlin-gradle-test-fail: build passed, tests is fail and names CalcTest",
          ok=_entry(rep, "build").get("status") == "pass"
          and e.get("status") == "fail" and "CalcTest" in _tail(e),
          detail=f"tests={e}")

    e = _entry(reports.get("kotlin-gradle-lint-fail"), "lint")
    check("kotlin-gradle-lint-fail: lint is fail and output names Calc.kt",
          ok=e.get("status") == "fail" and "Calc.kt" in _tail(e), detail=f"entry={e}")

    e = _entry(reports.get("kotlin-gradle-no-tests"), "tests")
    check("kotlin-gradle-no-tests: tests skipped with reason no_tests_found",
          ok=e.get("status") == "skipped" and e.get("reason") == "no_tests_found", detail=f"entry={e}")

    e = _entry(reports.get("kotlin-gradle-no-linter"), "lint")
    check("kotlin-gradle-no-linter: lint status is no_linter_configured",
          ok=e.get("status") == "no_linter_configured", detail=f"entry={e}")

    rep = reports.get("kotlin-gradle-multi")
    projects = (rep or {}).get("projects") or []
    check("kotlin-gradle-multi: report has one project (subprojects are part of the root)",
          ok=len(projects) == 1 and _entry(rep, "tests").get("status") == "pass",
          detail=f"projects={[p.get('path') for p in projects]}")

    # --- wrapper: fake gradlew scripts, no Gradle needed -----------------------
    wrapper = "gradlew.bat" if _WIN else "gradlew"
    marker = "fixture gradlew.bat assemble" if _WIN else "fixture gradlew (sh) assemble"
    code, out, err, rep = _run("kotlin-gradle-wrapper", tmp)
    check("kotlin-gradle-wrapper: table cells PASS WARN PASS SKIP, exit 0",
          ok=_cells(out) == ["PASS", "WARN", "PASS", "SKIP"] and code == 0,
          detail=f"exit={code} got {_cells(out)}\n{out}{err}", real=False)
    e = _entry(rep, "build")
    check(f"kotlin-gradle-wrapper: build ran {wrapper} (output has '{marker}')",
          ok=e.get("command") == [wrapper, "assemble"] and marker in _tail(e),
          detail=f"entry={e}", real=False)
    runners = ((rep or {}).get("environment") or {}).get("runners", {})
    check("kotlin-gradle-wrapper: environment does not claim the gradle on PATH ran",
          # the environment key drops .bat: "gradlew.bat" -> "gradlew"
          ok="gradle" not in runners and runners.get("gradlew") == "unknown",
          detail=f"runners={runners}", real=False)


# ---------------------------------------------------------------------------
# Go: real go / golangci-lint runs
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _env(**values: str):
    """Set environment variables for one run; restore the old values after."""
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# run name -> (fixture, edits, golangci needed, build, lint, tests, coverage, exit)
_GO_RUNS = {
    "go-ok": ("go-ok", None, False, "PASS", "PASS", "PASS", "100.0%", 0),
    "go-build-fail": ("go-build-fail", None, False, "FAIL", "SKIP", "SKIP", "SKIP", 1),
    "go-test-fail": ("go-test-fail", None, False, "PASS", "PASS", "FAIL", "FAIL", 1),
    "go-lint-fail": ("go-lint-fail", None, False, "PASS", "FAIL", "PASS", "100.0%", 1),
    "go-no-tests": ("go-no-tests", None, False, "PASS", "PASS", "SKIP", "0.0%", 0),
    "go-main": ("go-main", None, False, "PASS", "PASS", "PASS", "50.0%", 0),
    "go-missing-deps": ("go-missing-deps", None, False, "WARN", "WARN", "WARN", "WARN", 0),
    "go-old-toolchain": ("go-ok", [("go.mod", "go 1.18", "go 1.99")], False,
                         "WARN", "WARN", "WARN", "WARN", 0),
    "go-golangci-ok": ("go-golangci-ok", None, True, "PASS", "PASS", "PASS", "100.0%", 0),
    "go-golangci-nofix": ("go-golangci-nofix", None, True, "PASS", "FAIL", "PASS", "100.0%", 1),
}


def _go_checks(tmp: Path) -> None:
    no_go = "" if shutil.which("go") else "go is not on PATH"
    no_golangci = "" if shutil.which("golangci-lint") else "golangci-lint is not on PATH"

    def skip_reason(run: str) -> str:
        return no_go or (no_golangci if _GO_RUNS[run][2] else "")

    def check(run: str, text: str, *, ok: bool = False, detail: str = "") -> None:
        _check(f"{run}: {text}", ok=ok, detail=detail, skip=skip_reason(run), what="Go")

    envs = {
        # An empty module cache, so a copy of uuid cached on this PC cannot make it pass.
        "go-missing-deps": {"GOPROXY": "off", "GOTOOLCHAIN": "local",
                            "GOMODCACHE": str(tmp / "gomodcache")},
        "go-old-toolchain": {"GOTOOLCHAIN": "local"},
    }
    (tmp / "gomodcache").mkdir()

    reports: dict[str, dict | None] = {}
    for run, (fixture, edits, _, b, li, t, c, want_exit) in _GO_RUNS.items():
        want = [b, li, t, c]
        if skip_reason(run):
            check(run, f"one table row, cells {' '.join(want)}")
            check(run, f"exit code {want_exit}")
            continue
        print(f"      running {run} (real Go) ...", flush=True)
        with _env(**envs.get(run, {})):
            code, out, err, rep = _run(fixture, tmp, copy_name=run, edits=edits)
        reports[run] = rep
        check(run, f"one table row, cells {' '.join(want)}",
              ok=len(_rows(out)) == 1 and _cells(out) == want, detail=f"got {_rows(out)}\n{out}{err}")
        check(run, f"exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

    rep = reports.get("go-ok")
    e = _entry(rep, "build")
    null = "NUL" if _WIN else "/dev/null"
    check("go-ok", f"build command is go build -o {null} ./...",
          ok=e.get("command") == ["go", "build", "-o", null, "./..."] and e.get("status") == "pass",
          detail=f"entry={e}")
    results = (((rep or {}).get("projects") or [{}])[0].get("coverage") or {}).get("results", [])
    check("go-ok", "coverage read from coverage.out by the gocover reader (100.0)",
          ok=len(results) == 1 and results[0].get("source_file") == "coverage.out"
          and results[0].get("format") == "gocover" and results[0].get("line_pct") == 100.0,
          detail=f"results={results}")
    runners = ((rep or {}).get("environment") or {}).get("runners", {})
    check("go-ok", "environment records the go version",
          ok=runners.get("go", "unknown") != "unknown", detail=f"runners={runners}")

    rep = reports.get("go-build-fail")
    e = _entry(rep, "build")
    reasons = [_entry(rep, s).get("reason") for s in ("lint", "tests", "coverage")]
    check("go-build-fail", "build is fail (not dependencies_missing), the rest skipped by build_gate",
          ok=e.get("status") == "fail" and reasons == ["build_gate"] * 3,
          detail=f"entry={e} reasons={reasons}")

    e = _entry(reports.get("go-test-fail"), "tests")
    check("go-test-fail", "tests is fail and output names 'want 6'",
          ok=e.get("status") == "fail" and "want 6" in _tail(e), detail=f"tests={e}")

    e = _entry(reports.get("go-lint-fail"), "lint")
    check("go-lint-fail", "lint is fail and output names 'passes lock by value'",
          ok=e.get("status") == "fail" and "passes lock by value" in _tail(e), detail=f"entry={e}")

    e = _entry(reports.get("go-no-tests"), "tests")
    check("go-no-tests", "tests skipped with reason no_tests_found",
          ok=e.get("status") == "skipped" and e.get("reason") == "no_tests_found", detail=f"entry={e}")

    own = {p.name for p in (_FIXTURES / "go-main").iterdir()}
    left = {p.name for p in (tmp / "go-main").iterdir()} if (tmp / "go-main").exists() else set()
    check("go-main", "no program file written (only fixture files, coverage.out, .pre-llm)",
          ok=left == own | {"coverage.out", ".pre-llm"}, detail=f"extra={sorted(left - own)}")

    for run in ("go-missing-deps", "go-old-toolchain"):
        rep = reports.get(run)
        project = ((rep or {}).get("projects") or [{}])[0]
        failed = [c.get("stage") for c in project.get("commands", []) if c.get("status") == "fail"]
        check(run, "build is dependencies_missing, project warning dependencies_missing, nothing fail",
              ok=_entry(rep, "build").get("status") == "dependencies_missing"
              and "dependencies_missing" in (project.get("warnings") or []) and not failed,
              detail=f"build={_entry(rep, 'build')} warnings={project.get('warnings')} failed={failed}")

    e = _entry(reports.get("go-golangci-ok"), "lint")
    check("go-golangci-ok", "lint command is golangci-lint run --fix=false, status pass",
          ok=e.get("command") == ["golangci-lint", "run", "--fix=false"] and e.get("status") == "pass",
          detail=f"entry={e}")

    e = _entry(reports.get("go-golangci-nofix"), "lint")
    copy = tmp / "go-golangci-nofix" / "calc.go"
    same = copy.exists() and copy.read_bytes() == (_FIXTURES / "go-golangci-nofix" / "calc.go").read_bytes()
    check("go-golangci-nofix", "lint is fail and calc.go is unchanged (golangci-lint fixed nothing)",
          ok=e.get("status") == "fail" and same, detail=f"calc.go unchanged={same} entry={e}")


# ---------------------------------------------------------------------------
# C#: real dotnet runs
# ---------------------------------------------------------------------------

# run name -> (fixture, edits, build, lint, tests, coverage, exit)
_CSHARP_RUNS = {
    "csharp-ok": ("csharp-ok", None, "PASS", "PASS", "PASS", "100.0%", 0),
    "csharp-build-fail": ("csharp-build-fail", None, "FAIL", "SKIP", "SKIP", "SKIP", 1),
    "csharp-test-fail": ("csharp-test-fail", None, "PASS", "PASS", "FAIL", "FAIL", 1),
    "csharp-lint-fail": ("csharp-lint-fail", None, "PASS", "FAIL", "PASS", "100.0%", 1),
    "csharp-no-tests": ("csharp-no-tests", None, "PASS", "PASS", "SKIP", "SKIP", 0),
    "csharp-missing-deps": ("csharp-ok", None, "WARN", "WARN", "WARN", "WARN", 0),
    "csharp-old-sdk": ("csharp-no-tests", [("Calc.csproj", "net8.0", "net99.0")],
                       "WARN", "WARN", "WARN", "SKIP", 0),
}


def _csharp_checks(tmp: Path) -> None:
    no_dotnet = "" if shutil.which("dotnet") else "dotnet is not on PATH"

    def check(run: str, text: str, *, ok: bool = False, detail: str = "") -> None:
        _check(f"{run}: {text}", ok=ok, detail=detail, skip=no_dotnet, what=".NET")

    envs = {
        # An empty package cache, so packages cached on this PC cannot make it pass, and
        # a feed folder that does not exist (MSBuild reads environment variables as
        # properties, so restore looks only there and fails with NU1301).
        "csharp-missing-deps": {"NUGET_PACKAGES": str(tmp / "nugetpkgs"),
                                "RestoreSources": str(tmp / "nofeed")},
    }
    (tmp / "nugetpkgs").mkdir()

    reports: dict[str, dict | None] = {}
    for run, (fixture, edits, b, li, t, c, want_exit) in _CSHARP_RUNS.items():
        want = [b, li, t, c]
        if no_dotnet:
            check(run, f"one table row, cells {' '.join(want)}")
            check(run, f"exit code {want_exit}")
            continue
        print(f"      running {run} (real .NET) ...", flush=True)
        with _env(**envs.get(run, {})):
            code, out, err, rep = _run(fixture, tmp, copy_name=run, edits=edits)
        reports[run] = rep
        check(run, f"one table row, cells {' '.join(want)}",
              ok=len(_rows(out)) == 1 and _cells(out) == want, detail=f"got {_rows(out)}\n{out}{err}")
        check(run, f"exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

    rep = reports.get("csharp-ok")
    projects = (rep or {}).get("projects") or []
    check("csharp-ok", "report has one project '.' (the two .csproj are part of the solution)",
          ok=[p.get("path") for p in projects] == ["."],
          detail=f"projects={[p.get('path') for p in projects]}")
    e = _entry(rep, "build")
    check("csharp-ok", "build command is dotnet build App.sln",
          ok=e.get("command") == ["dotnet", "build", "App.sln"], detail=f"entry={e}")
    results = ((projects or [{}])[0].get("coverage") or {}).get("results", [])
    source = results[0].get("source_file", "") if len(results) == 1 else ""
    check("csharp-ok", "coverage read from Calc.Tests/TestResults/<guid>/coverage.cobertura.xml (100.0)",
          ok=len(results) == 1 and results[0].get("format") == "cobertura"
          and results[0].get("line_pct") == 100.0
          and source.startswith("Calc.Tests/TestResults/")
          and source.endswith("/coverage.cobertura.xml"),
          detail=f"results={results}")
    runners = ((rep or {}).get("environment") or {}).get("runners", {})
    check("csharp-ok", "environment records the dotnet version",
          ok=runners.get("dotnet", "unknown") != "unknown", detail=f"runners={runners}")

    rep = reports.get("csharp-build-fail")
    e = _entry(rep, "build")
    reasons = [_entry(rep, s).get("reason") for s in ("lint", "tests", "coverage")]
    check("csharp-build-fail", "build is fail (not dependencies_missing) and names CS1002, "
          "the rest skipped by build_gate",
          ok=e.get("status") == "fail" and "CS1002" in _tail(e) and reasons == ["build_gate"] * 3,
          detail=f"entry={e} reasons={reasons}")

    e = _entry(reports.get("csharp-test-fail"), "tests")
    check("csharp-test-fail", "tests is fail and output names 'Assert.Equal() Failure'",
          ok=e.get("status") == "fail" and "Assert.Equal() Failure" in _tail(e), detail=f"tests={e}")

    e = _entry(reports.get("csharp-lint-fail"), "lint")
    copy = tmp / "csharp-lint-fail" / "Calc" / "Calc.cs"
    original = _FIXTURES / "csharp-lint-fail" / "Calc" / "Calc.cs"
    same = copy.exists() and copy.read_bytes() == original.read_bytes()
    check("csharp-lint-fail", "lint is fail, names WHITESPACE, and Calc.cs is unchanged (dotnet format "
          "changed nothing)",
          ok=e.get("status") == "fail" and "WHITESPACE" in _tail(e) and same,
          detail=f"Calc.cs unchanged={same} entry={e}")

    rep = reports.get("csharp-no-tests")
    e = _entry(rep, "build")
    check("csharp-no-tests", "build command is dotnet build Calc.sln",
          ok=e.get("command") == ["dotnet", "build", "Calc.sln"], detail=f"entry={e}")
    e = _entry(rep, "lint")
    check("csharp-no-tests", "lint is pass (dotnet format names Calc.sln next to Calc.csproj)",
          ok=e.get("status") == "pass", detail=f"entry={e}")
    e = _entry(rep, "tests")
    check("csharp-no-tests", "tests skipped with reason no_tests_found",
          ok=e.get("status") == "skipped" and e.get("reason") == "no_tests_found", detail=f"entry={e}")

    for run in ("csharp-missing-deps", "csharp-old-sdk"):
        rep = reports.get(run)
        project = ((rep or {}).get("projects") or [{}])[0]
        failed = [c.get("stage") for c in project.get("commands", []) if c.get("status") == "fail"]
        check(run, "build is dependencies_missing, project warning dependencies_missing, nothing fail",
              ok=_entry(rep, "build").get("status") == "dependencies_missing"
              and "dependencies_missing" in (project.get("warnings") or []) and not failed,
              detail=f"build={_entry(rep, 'build')} warnings={project.get('warnings')} failed={failed}")


# ---------------------------------------------------------------------------
# Rust: real cargo runs
# ---------------------------------------------------------------------------

_TARPAULIN_ARGV = ["cargo", "tarpaulin", "--workspace", "--out", "Xml", "--output-dir", "."]

# run name -> (fixture, edits, build, lint, tests, coverage, exit)
_RUST_RUNS = {
    "rust-ok": ("rust-ok", None, "PASS", "PASS", "PASS", "SKIP", 0),
    "rust-build-fail": ("rust-build-fail", None, "FAIL", "SKIP", "SKIP", "SKIP", 1),
    "rust-test-fail": ("rust-test-fail", None, "PASS", "PASS", "FAIL", "SKIP", 1),
    "rust-lint-fail": ("rust-lint-fail", None, "PASS", "FAIL", "PASS", "SKIP", 1),
    "rust-no-tests": ("rust-no-tests", None, "PASS", "PASS", "SKIP", "SKIP", 0),
    "rust-workspace": ("rust-workspace", None, "PASS", "PASS", "PASS", "SKIP", 0),
    "rust-missing-deps": ("rust-missing-deps", None, "WARN", "WARN", "WARN", "SKIP", 0),
    "rust-old-toolchain": ("rust-ok", [("Cargo.toml", 'edition = "2021"',
                                        'edition = "2021"\nrust-version = "1.999"')],
                           "WARN", "WARN", "WARN", "SKIP", 0),
    # Run with a linker that does not exist (see _rust_checks): only tests links.
    "rust-no-linker": ("rust-ok", None, "PASS", "PASS", "WARN", "SKIP", 0),
    # Coverage cell is set in _rust_checks: a percentage with cargo-tarpaulin, else WARN.
    "rust-tarpaulin": ("rust-tarpaulin", None, "PASS", "PASS", "PASS", "", 0),
}


def _rust_checks(tmp: Path) -> None:
    no_cargo = "" if shutil.which("cargo") else "cargo is not on PATH"
    has_tarpaulin = shutil.which("cargo-tarpaulin") is not None

    def check(run: str, text: str, *, ok: bool = False, detail: str = "") -> None:
        _check(f"{run}: {text}", ok=ok, detail=detail, skip=no_cargo, what="Rust")

    runs = dict(_RUST_RUNS)
    fixture, edits, b, li, t, _, want_exit = runs["rust-tarpaulin"]
    runs["rust-tarpaulin"] = (fixture, edits, b, li, t, _PCT if has_tarpaulin else "WARN", want_exit)

    envs = {
        # Offline, with an empty cargo home, so a copy of itoa cached on this PC
        # cannot make it pass (and no internet is needed).
        "rust-missing-deps": {"CARGO_NET_OFFLINE": "true", "CARGO_HOME": str(tmp / "cargohome")},
        # A linker that does not exist, as on Windows without the C++ Build Tools
        # (needs no real linker, so it works on any PC with cargo).
        "rust-no-linker": {"RUSTFLAGS": "-C linker=pre-llm-no-such-linker"},
    }
    (tmp / "cargohome").mkdir()

    reports: dict[str, dict | None] = {}
    for run, (fixture, edits, b, li, t, c, want_exit) in runs.items():
        want = [b, li, t, c]
        if no_cargo:
            check(run, f"one table row, cells {' '.join(want)}")
            check(run, f"exit code {want_exit}")
            continue
        if run == "rust-tarpaulin":
            print("      cargo-tarpaulin found" if has_tarpaulin
                  else "      cargo-tarpaulin not installed: checking the warning instead", flush=True)
        print(f"      running {run} (real cargo) ...", flush=True)
        with _env(**envs.get(run, {})):
            code, out, err, rep = _run(fixture, tmp, copy_name=run, edits=edits)
        reports[run] = rep
        check(run, f"one table row, cells {' '.join(want)}",
              ok=len(_rows(out)) == 1 and _cells_match(_cells(out), want),
              detail=f"got {_rows(out)}\n{out}{err}")
        check(run, f"exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

    rep = reports.get("rust-ok")
    e = _entry(rep, "build")
    check("rust-ok", "build command is cargo build --workspace, status pass",
          ok=e.get("command") == ["cargo", "build", "--workspace"] and e.get("status") == "pass",
          detail=f"entry={e}")
    runners = ((rep or {}).get("environment") or {}).get("runners", {})
    check("rust-ok", "environment records the cargo version",
          ok=runners.get("cargo", "unknown") != "unknown", detail=f"runners={runners}")
    own = {p.name for p in (_FIXTURES / "rust-ok").iterdir()}
    left = {p.name for p in (tmp / "rust-ok").iterdir()} if (tmp / "rust-ok").exists() else set()
    check("rust-ok", "copy holds only fixture files, Cargo.lock, target, .pre-llm",
          ok=left == own | {"Cargo.lock", "target", ".pre-llm"},
          detail=f"extra={sorted(left - own)} missing={sorted(own - left)}")

    rep = reports.get("rust-build-fail")
    e = _entry(rep, "build")
    reasons = [_entry(rep, s).get("reason") for s in ("lint", "tests", "coverage")]
    check("rust-build-fail", "build is fail (not dependencies_missing), the rest skipped by build_gate",
          ok=e.get("status") == "fail" and reasons == ["build_gate"] * 3,
          detail=f"entry={e} reasons={reasons}")

    e = _entry(reports.get("rust-test-fail"), "tests")
    check("rust-test-fail", "tests is fail and output names 'right: 6'",
          ok=e.get("status") == "fail" and "right: 6" in _tail(e), detail=f"tests={e}")

    e = _entry(reports.get("rust-lint-fail"), "lint")
    check("rust-lint-fail", "lint is fail and output names needless_return",
          ok=e.get("status") == "fail" and "needless_return" in _tail(e), detail=f"entry={e}")

    e = _entry(reports.get("rust-no-tests"), "tests")
    check("rust-no-tests", "tests skipped with reason no_tests_found",
          ok=e.get("status") == "skipped" and e.get("reason") == "no_tests_found", detail=f"entry={e}")

    rep = reports.get("rust-workspace")
    projects = (rep or {}).get("projects") or []
    tail = _tail(_entry(rep, "tests"))
    check("rust-workspace", "report has one project '.' and tests ran member_a_adds and member_b_adds",
          ok=[p.get("path") for p in projects] == ["."]
          and "member_a_adds" in tail and "member_b_adds" in tail,
          detail=f"projects={[p.get('path') for p in projects]} tests tail={tail!r}")

    for run in ("rust-missing-deps", "rust-old-toolchain"):
        rep = reports.get(run)
        project = ((rep or {}).get("projects") or [{}])[0]
        failed = [c.get("stage") for c in project.get("commands", []) if c.get("status") == "fail"]
        check(run, "build is dependencies_missing, project warning dependencies_missing, nothing fail",
              ok=_entry(rep, "build").get("status") == "dependencies_missing"
              and "dependencies_missing" in (project.get("warnings") or []) and not failed,
              detail=f"build={_entry(rep, 'build')} warnings={project.get('warnings')} failed={failed}")

    e = _entry(reports.get("rust-old-toolchain"), "build")
    check("rust-old-toolchain", "build output names 'requires rustc 1.999'",
          ok="requires rustc 1.999" in _tail(e), detail=f"entry={e}")

    rep = reports.get("rust-no-linker")
    project = ((rep or {}).get("projects") or [{}])[0]
    failed = [c.get("stage") for c in project.get("commands", []) if c.get("status") == "fail"]
    e = _entry(rep, "tests")
    check("rust-no-linker", "tests is dependencies_missing and names 'linker `pre-llm-no-such-linker` not found', "
          "project warning dependencies_missing, nothing fail",
          ok=e.get("status") == "dependencies_missing"
          and "linker `pre-llm-no-such-linker` not found" in _tail(e)
          and "dependencies_missing" in (project.get("warnings") or []) and not failed,
          detail=f"tests={e} warnings={project.get('warnings')} failed={failed}")

    rep = reports.get("rust-tarpaulin")
    e = _entry(rep, "coverage")
    if has_tarpaulin:
        check("rust-tarpaulin", "coverage command is " + " ".join(_TARPAULIN_ARGV) + ", status pass",
              ok=e.get("command") == _TARPAULIN_ARGV and e.get("status") == "pass", detail=f"entry={e}")
        results = (((rep or {}).get("projects") or [{}])[0].get("coverage") or {}).get("results", [])
        r = results[0] if len(results) == 1 else {}
        check("rust-tarpaulin", "coverage read from cobertura.xml (line_pct > 0, branch_pct null)",
              ok=r.get("source_file") == "cobertura.xml" and r.get("format") == "cobertura"
              and (r.get("line_pct") or 0) > 0 and "branch_pct" in r and r["branch_pct"] is None,
              detail=f"results={results}")
    else:
        check("rust-tarpaulin", "coverage is dependencies_missing and names 'no such command: `tarpaulin`'",
              ok=e.get("status") == "dependencies_missing" and "no such command: `tarpaulin`" in _tail(e),
              detail=f"entry={e}")


# ---------------------------------------------------------------------------
# PHP: real php / composer runs
# ---------------------------------------------------------------------------

# True when PCOV or Xdebug (in coverage mode) can collect coverage.
_PHP_DRIVER_CODE = (
    "echo ((extension_loaded('pcov') && ini_get('pcov.enabled')) || "
    "(extension_loaded('xdebug') && function_exists('xdebug_info') && "
    "in_array('coverage', xdebug_info('mode')))) ? 'yes' : 'no';"
)

_PHPUNIT_TESTS_ARGV = ["vendor/bin/phpunit", "--no-coverage", "--do-not-cache-result"]

# run name -> (fixture, needs (php, composer, vendor), build, lint, tests,
#              coverage with a driver, coverage without one, exit)
# "needs": "unit" = php + composer + the shared vendor/; "composer" = php + composer;
# "php" = php only; "" = nothing.
_PHP_RUNS = {
    "php-unit-ok": ("php-unit-ok", "unit", "SKIP", "PASS", "PASS", "100.0%", "WARN", 0),
    "php-unit-test-fail": ("php-unit-test-fail", "unit", "SKIP", "PASS", "FAIL", "FAIL", "WARN", 1),
    "php-unit-lint-fail": ("php-unit-lint-fail", "unit", "SKIP", "FAIL", "PASS", "100.0%", "WARN", 1),
    "php-unit-no-tests": ("php-unit-no-tests", "unit", "SKIP", "PASS", "SKIP", _PCT, "WARN", 0),
    "php-unit-missing-deps": ("php-unit-ok", "", "SKIP", "SKIP", "SKIP", "SKIP", "SKIP", 0),
    "php-scripts": ("php-scripts", "composer", "SKIP", "PASS", "PASS", "SKIP", "SKIP", 0),
    "php-fixer-script": ("php-fixer-script", "composer", "SKIP", "WARN", "PASS", "SKIP", "SKIP", 0),
    "php-ok": ("php-ok", "php", "SKIP", "PASS", "PASS", "SKIP", "SKIP", 0),
    "php-test-fail": ("php-test-fail", "php", "SKIP", "PASS", "FAIL", "SKIP", "SKIP", 1),
    "php-lint-fail": ("php-lint-fail", "php", "SKIP", "FAIL", "PASS", "SKIP", "SKIP", 1),
    "php-no-tests": ("php-no-tests", "php", "SKIP", "PASS", "SKIP", "SKIP", "SKIP", 0),
    "php-no-linter": ("php-no-linter", "php", "SKIP", "WARN", "PASS", "SKIP", "SKIP", 0),
}


def _php_has_coverage_driver() -> bool:
    try:
        proc = subprocess.run([shutil.which("php"), "-r", _PHP_DRIVER_CODE], shell=False,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.stdout.strip() == "yes"


def _php_install_toolbox(toolbox: Path) -> str:
    """composer install PHPUnit and PHP_CodeSniffer once into *toolbox*; return a skip reason or ""."""
    shutil.copytree(_FIXTURES / "php-unit-ok", toolbox)
    print("      installing PHPUnit and PHP_CodeSniffer with composer "
          "(the first time this downloads, can take a few minutes) ...", flush=True)
    try:
        proc = subprocess.run([shutil.which("composer"), "install", "--no-interaction", "--no-progress"],
                              shell=False, cwd=toolbox, env={**os.environ, "COMPOSER_NO_INTERACTION": "1"},
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"composer install failed: {exc}"
    if proc.returncode != 0 or not (toolbox / "vendor" / "autoload.php").is_file():
        lines = [ln.strip() for ln in (proc.stdout + "\n" + proc.stderr).splitlines() if ln.strip()]
        return f"composer install failed: {lines[-1] if lines else f'exit {proc.returncode}'}"
    return ""


def _php_checks(tmp: Path) -> None:
    no_php = "" if shutil.which("php") else "php is not on PATH"
    no_composer = no_php or ("" if shutil.which("composer") else "composer is not on PATH")
    driver = False
    if not no_php:
        driver = _php_has_coverage_driver()
        print("      coverage driver found: expecting a percentage" if driver
              else "      no coverage driver (PCOV/Xdebug): expecting the WARN", flush=True)

    toolbox = tmp / "php-toolbox"
    no_vendor = no_composer or _php_install_toolbox(toolbox)

    def skip_reason(run: str) -> str:
        needs = _PHP_RUNS[run][1]
        return {"unit": no_vendor, "composer": no_composer, "php": no_php}.get(needs, "")

    def check(run: str, text: str, *, ok: bool = False, detail: str = "") -> None:
        _check(f"{run}: {text}", ok=ok, detail=detail, skip=skip_reason(run), what="PHP")

    def add_vendor(work: Path) -> None:
        # Composer's autoloader uses paths relative to vendor/, so a copy works
        # in any php-unit fixture (all share the same autoload setting).
        shutil.copytree(toolbox / "vendor", work / "vendor", symlinks=True)

    reports: dict[str, dict | None] = {}
    for run, (fixture, needs, b, li, t, c_driver, c_none, want_exit) in _PHP_RUNS.items():
        c = c_driver if driver else c_none
        want = [b, li, t, c]
        label = f"one table row, cells {' '.join(want)}"
        if run == "php-unit-no-tests" and driver:
            label = f"one table row, cells {b} {li} {t} <percent> or WARN"
        if skip_reason(run):
            check(run, label)
            check(run, f"exit code {want_exit}")
            continue
        print(f"      running {run} (real PHP) ...", flush=True)
        prepare = add_vendor if needs == "unit" else None
        code, out, err, rep = _run(fixture, tmp, copy_name=run, prepare=prepare)
        reports[run] = rep
        cells = _cells(out)
        ok = len(_rows(out)) == 1 and _cells_match(cells, want)
        if run == "php-unit-no-tests" and driver:
            ok = ok or (len(_rows(out)) == 1 and cells == [b, li, t, "WARN"])
        check(run, label, ok=ok, detail=f"got {_rows(out)}\n{out}{err}")
        check(run, f"exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")

    # --- php-unit-ok ---------------------------------------------------------
    rep = reports.get("php-unit-ok")
    e = _entry(rep, "tests")
    check("php-unit-ok", "tests command is " + " ".join(_PHPUNIT_TESTS_ARGV) + ", status pass",
          ok=e.get("command") == _PHPUNIT_TESTS_ARGV and e.get("status") == "pass", detail=f"entry={e}")
    e = _entry(rep, "lint")
    check("php-unit-ok", "lint command is vendor/bin/phpcs, status pass",
          ok=e.get("command") == ["vendor/bin/phpcs"] and e.get("status") == "pass", detail=f"entry={e}")
    cache = tmp / "php-unit-ok" / ".phpunit.result.cache"
    check("php-unit-ok", "no .phpunit.result.cache written into the copy",
          ok=(tmp / "php-unit-ok").exists() and not cache.exists(), detail=f"{cache} exists")
    e = _entry(rep, "coverage")
    if driver:
        results = (((rep or {}).get("projects") or [{}])[0].get("coverage") or {}).get("results", [])
        r = results[0] if len(results) == 1 else {}
        check("php-unit-ok", "coverage read from clover.xml by the clover reader (100.0)",
              ok=r.get("source_file") == "clover.xml" and r.get("format") == "clover"
              and r.get("line_pct") == 100.0, detail=f"results={results}")
    else:
        check("php-unit-ok", "coverage is dependencies_missing and names 'No code coverage driver'",
              ok=e.get("status") == "dependencies_missing" and "No code coverage driver" in _tail(e),
              detail=f"entry={e}")

    # --- php-unit-test-fail ----------------------------------------------------
    e = _entry(reports.get("php-unit-test-fail"), "tests")
    check("php-unit-test-fail", "tests is fail and output names 'Failed asserting that 5 is identical to 6'",
          ok=e.get("status") == "fail" and "Failed asserting that 5 is identical to 6" in _tail(e),
          detail=f"entry={e}")

    # --- php-unit-lint-fail ----------------------------------------------------
    e = _entry(reports.get("php-unit-lint-fail"), "lint")
    copy = tmp / "php-unit-lint-fail" / "src" / "Calc.php"
    same = copy.exists() and copy.read_bytes() == (_FIXTURES / "php-unit-lint-fail" / "src" / "Calc.php").read_bytes()
    check("php-unit-lint-fail", "lint is fail, names 'must be followed by a single space', src/Calc.php unchanged",
          ok=e.get("status") == "fail" and "must be followed by a single space" in _tail(e) and same,
          detail=f"Calc.php unchanged={same} entry={e}")

    # --- php-unit-no-tests -----------------------------------------------------
    e = _entry(reports.get("php-unit-no-tests"), "tests")
    check("php-unit-no-tests", "tests skipped with reason no_tests_found",
          ok=e.get("status") == "skipped" and e.get("reason") == "no_tests_found", detail=f"entry={e}")

    # --- php-unit-missing-deps -------------------------------------------------
    rep = reports.get("php-unit-missing-deps")
    project = ((rep or {}).get("projects") or [{}])[0]
    entries = project.get("commands") or []
    check("php-unit-missing-deps", "every stage skipped with reason dependencies_missing, project warning",
          ok=bool(entries) and all(c.get("status") == "skipped"
                                   and str(c.get("reason", "")).startswith("dependencies_missing")
                                   for c in entries)
          and "dependencies_missing" in (project.get("warnings") or []),
          detail=f"commands={entries} warnings={project.get('warnings')}")

    # --- php-scripts -----------------------------------------------------------
    rep = reports.get("php-scripts")
    project = ((rep or {}).get("projects") or [{}])[0]
    lint, tests = _entry(rep, "lint"), _entry(rep, "tests")
    check("php-scripts", "composer lint and composer test both pass, no dependencies_missing warning",
          ok=lint.get("command") == ["composer", "lint"] and lint.get("status") == "pass"
          and tests.get("command") == ["composer", "test"] and tests.get("status") == "pass"
          and "dependencies_missing" not in (project.get("warnings") or []),
          detail=f"lint={lint} tests={tests} warnings={project.get('warnings')}")

    # --- php-fixer-script ------------------------------------------------------
    rep = reports.get("php-fixer-script")
    lint, tests = _entry(rep, "lint"), _entry(rep, "tests")
    copy = tmp / "php-fixer-script" / "calc.php"
    same = copy.exists() and copy.read_bytes() == (_FIXTURES / "php-fixer-script" / "calc.php").read_bytes()
    check("php-fixer-script", "lint is no_linter_configured, composer test passes, calc.php unchanged",
          ok=lint.get("status") == "no_linter_configured"
          and tests.get("command") == ["composer", "test"] and tests.get("status") == "pass" and same,
          detail=f"calc.php unchanged={same} lint={lint} tests={tests}")

    # --dry-run needs no php: the fixer scripts are listed as skipped.
    code, out, err, _ = _run("php-fixer-script", tmp, ["--dry-run"], copy_name="php-fixer-script-dry")
    lines = {ln.strip() for ln in out.splitlines()}
    want = {"skipped: lint  (command runs a fixer)", "skipped: cs  (command runs a fixer)"}
    _check("php-fixer-script: --dry-run lists lint and cs as skipped (command runs a fixer)",
           ok=want <= lines and code == 0, detail=f"exit={code}\n{out}{err}")


LANGS: dict[str, Lang] = {
    "csharp": Lang(
        detect={
            "csharp-detect": [
                "build: dotnet build App.Tests.csproj  [builtin]",
                "lint: dotnet format App.Tests.csproj --verify-no-changes  [builtin]",
                "tests: dotnet test App.Tests.csproj  [builtin]",
                "coverage: dotnet test App.Tests.csproj --collect:XPlat Code Coverage  [config]",
            ]
        },
        custom=_csharp_checks,
    ),
    "go": Lang(
        detect={
            "go-detect": [
                "build: go build -o /dev/null ./...  [builtin]",
                "lint: golangci-lint run --fix=false  [config]",
                "tests: go test ./...  [builtin]",
                "coverage: go test -coverprofile=coverage.out ./...  [builtin]",
            ]
        },
        custom=_go_checks,
    ),
    "kotlin": Lang(
        detect={
            "kotlin-detect": [
                "build: gradle assemble  [builtin]",
                "lint: gradle detekt  [config]",
                "tests: gradle test  [builtin]",
                "coverage: gradle jacocoTestReport  [config]",
            ]
        },
        custom=_kotlin_checks,
    ),
    "php": Lang(
        detect={
            "php-detect": [
                "lint: vendor/bin/phpcs  [config]",
                "lint: vendor/bin/phpstan analyse  [config]",
                "tests: vendor/bin/phpunit --no-coverage --do-not-cache-result  [config]",
                "coverage: vendor/bin/phpunit --do-not-cache-result --coverage-clover clover.xml  [config]",
            ]
        },
        custom=_php_checks,
    ),
    "rust": Lang(
        detect={
            "rust-detect": [
                "build: cargo build --workspace  [builtin]",
                "lint: cargo clippy --workspace  [builtin]",
                "tests: cargo test --workspace  [builtin]",
                "coverage: cargo tarpaulin --workspace --out Xml --output-dir .  [config]",
            ]
        },
        custom=_rust_checks,
    ),
}


def run_checks(selected: list[str]) -> int:
    os.chdir(_REPO_ROOT)
    for lang in selected:
        spec = LANGS[lang]
        print(f"\n== {lang} ==")
        missing = [t for t in spec.tools if shutil.which(t) is None]
        # ignore_cleanup_errors: a Gradle daemon may still hold a file in the copy.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            tmp = Path(td)
            for name, (b, li, t, c, want_exit) in spec.execution.items():
                if missing:
                    reason = f"{', '.join(missing)} not on PATH"
                    _check(f"{name}: table cells {b} {li} {t} {c}", ok=False, skip=reason)
                    _check(f"{name}: exit code {want_exit}", ok=False, skip=reason)
                    continue
                code, out, err, _ = _run(name, tmp, prepare=spec.prepare)
                _check(f"{name}: table cells {b} {li} {t} {c}",
                       ok=_cells(out) == [b, li, t, c], detail=f"got {_cells(out)}\n{out}{err}")
                _check(f"{name}: exit code {want_exit}", ok=code == want_exit, detail=f"got {code}")
            if spec.custom:
                spec.custom(tmp)
            for name, want in spec.detect.items():
                code, out, err, _ = _run(name, tmp, ["--dry-run"])
                got = [
                    ln.strip()
                    for ln in out.splitlines()
                    if ln.strip().split(":")[0] in _STAGES
                ]
                _check(f"{name}: --dry-run lists exactly the expected stage commands",
                       ok=got == want and code == 0, detail=f"exit={code}\n{out}{err}")

    print()
    passed, total = _counts["PASS"], _counts["PASS"] + _counts["FAIL"]
    notes = "; ".join(f"{count} {key}" for key, count in _skip_notes.items())
    note = f" ({notes})" if notes else ""
    print(f"{'All checks passed' if not _counts['FAIL'] else 'Some checks FAILED'}: {passed}/{total}{note}")
    return 1 if _counts["FAIL"] else 0


if __name__ == "__main__":
    args = sys.argv[1:] or list(LANGS)
    unknown = [a for a in args if a not in LANGS]
    if unknown:
        print(f"unknown language(s): {', '.join(unknown)}; choose from {', '.join(LANGS)}")
        sys.exit(2)
    sys.exit(run_checks(args))
