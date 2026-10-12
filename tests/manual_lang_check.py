"""Manual per-language fixture checks (Sessions 13+).

Run as:
    python tests/manual_lang_check.py            # every language
    python tests/manual_lang_check.py go rust    # only these

For each language: execution fixtures are copied to a temp folder, run through
pre_llm_checks.main(), and compared with the table cells and exit code in
tests/fixtures/EXPECTED.md; detect fixtures are checked with --dry-run (nothing
is installed or executed).  A language whose toolchain is not on PATH is
reported as SKIP (not FAIL) for its execution fixtures; detect fixtures never
need the toolchain.

Exit code: 0 if no check FAILED, 1 otherwise.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
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


@dataclass
class Lang:
    tools: list[str] = field(default_factory=list)  # must all be on PATH for execution fixtures
    # fixture -> (build, lint, tests, coverage, exit code)
    execution: dict[str, tuple[str, str, str, str, int]] = field(default_factory=dict)
    # fixture -> expected dry-run stage lines
    detect: dict[str, list[str]] = field(default_factory=dict)
    prepare: Optional[Callable[[Path], None]] = None  # e.g. create vendor/ in the copy


LANGS: dict[str, Lang] = {
    "swift": Lang(
        tools=["swift", "swiftc"],
        execution={
            "swift-ok": ("PASS", "PASS", "PASS", "SKIP", 0),
            "swift-build-fail": ("FAIL", "SKIP", "SKIP", "SKIP", 1),
            "swift-test-fail": ("PASS", "PASS", "FAIL", "SKIP", 1),
            "swift-lint-fail": ("PASS", "FAIL", "PASS", "SKIP", 1),
            "swift-no-linter": ("PASS", "WARN", "PASS", "SKIP", 0),
        },
        detect={
            "swift-detect": [
                "build: swift build  [builtin]",
                "lint: swiftlint  [config]",
                "lint: swiftformat --lint .  [config]",
                "tests: swift test  [builtin]",
            ]
        },
    ),
    "ruby": Lang(
        tools=["ruby"],
        execution={
            "ruby-ok": ("SKIP", "PASS", "PASS", "SKIP", 0),
            "ruby-test-fail": ("SKIP", "PASS", "FAIL", "SKIP", 1),
            "ruby-lint-fail": ("SKIP", "FAIL", "PASS", "SKIP", 1),
            "ruby-no-tests": ("SKIP", "PASS", "SKIP", "SKIP", 0),
            "ruby-no-linter": ("SKIP", "WARN", "PASS", "SKIP", 0),
        },
        detect={
            "ruby-detect": [
                "lint: bundle exec rubocop  [config]",
                "tests: bundle exec rspec  [config]",
                "coverage: bundle exec rspec  [config]",
            ]
        },
    ),
    "php": Lang(
        tools=["php"],
        execution={
            "php-ok": ("SKIP", "PASS", "PASS", "SKIP", 0),
            "php-test-fail": ("SKIP", "PASS", "FAIL", "SKIP", 1),
            "php-lint-fail": ("SKIP", "FAIL", "PASS", "SKIP", 1),
            "php-no-tests": ("SKIP", "PASS", "SKIP", "SKIP", 0),
            "php-no-linter": ("SKIP", "WARN", "PASS", "SKIP", 0),
        },
        detect={
            "php-detect": [
                "lint: vendor/bin/phpcs  [config]",
                "lint: vendor/bin/phpstan analyse  [config]",
                "tests: vendor/bin/phpunit  [config]",
                "coverage: vendor/bin/phpunit --coverage-clover clover.xml  [config]",
            ]
        },
    ),
    "rust": Lang(
        tools=["cargo"],
        execution={
            "rust-ok": ("PASS", "PASS", "PASS", "SKIP", 0),
            "rust-build-fail": ("FAIL", "SKIP", "SKIP", "SKIP", 1),
            "rust-test-fail": ("PASS", "PASS", "FAIL", "SKIP", 1),
            "rust-lint-fail": ("PASS", "FAIL", "PASS", "SKIP", 1),
        },
        detect={
            "rust-detect": [
                "build: cargo build  [builtin]",
                "lint: cargo clippy  [builtin]",
                "tests: cargo test  [builtin]",
                "coverage: cargo tarpaulin --out Xml  [config]",
            ]
        },
    ),
    "csharp": Lang(
        detect={
            "csharp-detect": [
                "build: dotnet build  [builtin]",
                "lint: dotnet format --verify-no-changes  [builtin]",
                "tests: dotnet test  [builtin]",
                "coverage: dotnet test --collect:XPlat Code Coverage  [config]",
            ]
        }
    ),
    "go": Lang(
        tools=["go"],
        execution={
            "go-ok": ("PASS", "PASS", "PASS", "100.0%", 0),
            "go-build-fail": ("FAIL", "SKIP", "SKIP", "SKIP", 1),
            "go-test-fail": ("PASS", "PASS", "FAIL", "FAIL", 1),
            "go-lint-fail": ("PASS", "FAIL", "PASS", "100.0%", 1),
        },
        detect={
            "go-detect": [
                "build: go build ./...  [builtin]",
                "lint: golangci-lint run  [config]",
                "tests: go test ./...  [builtin]",
                "coverage: go test -coverprofile=coverage.out ./...  [builtin]",
            ]
        },
    ),
    "kotlin": Lang(
        detect={
            "kotlin-detect": [
                "build: gradle build  [builtin]",
                "lint: gradle detekt  [config]",
                "tests: gradle test  [builtin]",
                "coverage: gradle jacocoTestReport  [config]",
            ]
        }
    ),
}

_counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
_n = 0


def _report(label: str, text: str, detail: str = "") -> None:
    global _n
    _n += 1
    _counts[label] += 1
    suffix = f"  ({detail})" if detail and label == "FAIL" else ""
    print(f"{label}  {_n:2d}. {text}{suffix}")


def _run(name: str, tmp: Path, extra: list[str] | None = None, prepare=None):
    work = tmp / name
    shutil.copytree(_FIXTURES / name, work)
    if prepare:
        prepare(work)
    report_path = tmp / f"report_{name}.json"
    argv = ["--path", str(work), "--output", str(report_path), *(extra or [])]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pre_llm_checks.main(argv)
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None else 0
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    return code, out.getvalue(), err.getvalue(), report


def _cells(stdout: str) -> list[str]:
    for line in stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["."]:
            return parts[-4:]
    return []


def run_checks(selected: list[str]) -> int:
    os.chdir(_REPO_ROOT)
    for lang in selected:
        spec = LANGS[lang]
        print(f"\n== {lang} ==")
        missing = [t for t in spec.tools if shutil.which(t) is None]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for name, (b, li, t, c, want_exit) in spec.execution.items():
                if missing:
                    _report("SKIP", f"{name}: needs {', '.join(missing)} on PATH")
                    continue
                code, out, err, _ = _run(name, tmp, prepare=spec.prepare)
                _report(
                    "PASS" if _cells(out) == [b, li, t, c] else "FAIL",
                    f"{name}: table cells {b} {li} {t} {c}",
                    f"got {_cells(out)}\n{out}{err}",
                )
                _report(
                    "PASS" if code == want_exit else "FAIL",
                    f"{name}: exit code {want_exit}",
                    f"got {code}",
                )
            for name, want in spec.detect.items():
                code, out, err, _ = _run(name, tmp, ["--dry-run"])
                got = [
                    ln.strip()
                    for ln in out.splitlines()
                    if ln.strip().split(":")[0] in _STAGES
                ]
                _report(
                    "PASS" if got == want and code == 0 else "FAIL",
                    f"{name}: --dry-run lists exactly the expected stage commands",
                    f"exit={code}\n{out}{err}",
                )
    print(f"\nPASS {_counts['PASS']}  FAIL {_counts['FAIL']}  SKIP {_counts['SKIP']}")
    return 1 if _counts["FAIL"] else 0


if __name__ == "__main__":
    args = sys.argv[1:] or list(LANGS)
    unknown = [a for a in args if a not in LANGS]
    if unknown:
        print(f"unknown language(s): {', '.join(unknown)}; choose from {', '.join(LANGS)}")
        sys.exit(2)
    sys.exit(run_checks(args))
