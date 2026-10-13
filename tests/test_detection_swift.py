"""Tests for Swift detection and discovery (Session 19).

- Swift Package Manager only: `swift build`, `swift test` and
  `swift test --enable-code-coverage` are SwiftPM built-ins; nothing else is.
  An Xcode project (*.xcodeproj, a folder) is not a project.
- Lint runs only when the project has the tool's config file: SwiftLint
  (.swiftlint.yml only), SwiftFormat (.swiftformat, only `--lint`) and Apple's
  swift-format (.swift-format, with `--strict`).
- SwiftPM puts dependency checkouts (each with its own Package.swift) under
  `.build/`, which must not be discovered as projects.
- A package with no test target (`error: no tests found`, exit 1) and a test
  target with no tests (exit 0) are both SKIP, reason no_tests_found.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import DetectionResult, StageCommand, detect_commands
from discovery import Project, discover_projects
from orchestrator import OrchestratorOptions, _matches_dep_error, run_project
from pre_llm_checks import load_languages

_LANGS = load_languages()
_SWIFT = _LANGS["swift"]


def _proj(tmp_path: Path, extra: dict[str, str] | None = None) -> Project:
    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.5\n")
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="swift", primary_build_file="Package.swift")


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


_SWIFTLINT = ["swiftlint", "lint", "--quiet"]
_SWIFTFORMAT = ["swiftformat", "--lint", "."]
_SWIFT_FORMAT = ["swift", "format", "lint", "--strict", "--recursive", "."]


def test_bare_package_gets_swiftpm_builtins(tmp_path):
    r = detect_commands(_proj(tmp_path), _SWIFT)
    assert _argv(r, "build") == [["swift", "build"]]
    assert _argv(r, "tests") == [["swift", "test"]]
    assert _argv(r, "coverage") == [["swift", "test", "--enable-code-coverage"]]
    assert _argv(r, "lint") == []


def test_swiftlint_yml_adds_lint(tmp_path):
    r = detect_commands(_proj(tmp_path, {".swiftlint.yml": "disabled_rules: []"}), _SWIFT)
    assert _argv(r, "lint") == [_SWIFTLINT]
    assert r.commands["lint"][0].source == "config"


def test_swiftlint_yaml_alone_is_not_read_by_swiftlint(tmp_path):
    r = detect_commands(_proj(tmp_path, {".swiftlint.yaml": "disabled_rules: []"}), _SWIFT)
    assert _argv(r, "lint") == []


def test_swiftformat_runs_read_only(tmp_path):
    r = detect_commands(_proj(tmp_path, {".swiftformat": "--indent 4"}), _SWIFT)
    assert _argv(r, "lint") == [_SWIFTFORMAT]


def test_swiftformat_yml_alone_is_not_a_swiftformat_config(tmp_path):
    r = detect_commands(_proj(tmp_path, {"swiftformat.yml": "--indent 4"}), _SWIFT)
    assert _argv(r, "lint") == []


def test_swift_format_runs_strict(tmp_path):
    r = detect_commands(_proj(tmp_path, {".swift-format": '{ "version": 1 }'}), _SWIFT)
    assert _argv(r, "lint") == [_SWIFT_FORMAT]


def test_all_three_configured_run_in_rule_order(tmp_path):
    extra = {".swift-format": "{}", ".swiftformat": "", ".swiftlint.yml": ""}
    r = detect_commands(_proj(tmp_path, extra), _SWIFT)
    assert _argv(r, "lint") == [_SWIFTLINT, _SWIFTFORMAT, _SWIFT_FORMAT]


def test_swift_config_shape():
    assert "stage_names" not in _SWIFT and "config_files" not in _SWIFT
    assert _SWIFT["build_files"] == ["Package.swift"]
    assert _SWIFT["coverage_needs_tests"] is True
    assert _SWIFT["coverage_files"] == [".build/*/debug/codecov/*.json"]


def test_dot_build_checkouts_are_not_projects(tmp_path):
    (tmp_path / "Package.swift").write_text("")
    dep = tmp_path / ".build" / "checkouts" / "some-dep"
    dep.mkdir(parents=True)
    (dep / "Package.swift").write_text("")
    found = [p.path for p in discover_projects(tmp_path, _LANGS) if p.language == "swift"]
    assert found == [tmp_path]


def test_xcodeproj_alone_is_not_a_project(tmp_path):
    xcodeproj = tmp_path / "App.xcodeproj"
    xcodeproj.mkdir()
    (xcodeproj / "project.pbxproj").write_text("")
    (tmp_path / "main.swift").write_text('print("hi")\n')
    found = [p for p in discover_projects(tmp_path, _LANGS) if p.language == "swift"]
    assert found == []


# --- No tests ---------------------------------------------------------------------


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def _no_tests(text: str, key: str = "no_tests_patterns") -> bool:
    return _any(_SWIFT[key], text) and not _any(_SWIFT["tests_ran_patterns"], text)


def test_no_tests_patterns():
    assert _no_tests(
        "Test Suite 'All tests' passed at 2026-10-13 01:14:32.521\n"
        "\t Executed 0 tests, with 0 failures (0 unexpected) in 0.0 (0.0) seconds\n"
        "✔ Test run with 0 tests in 0 suites passed after 0.001 seconds."
    )
    # XCTest ran one
    assert not _no_tests(
        "\t Executed 1 test, with 0 failures (0 unexpected) in 0.001 (0.001) seconds\n"
        "✔ Test run with 0 tests in 0 suites passed after 0.001 seconds."
    )
    # swift-testing ran one
    assert not _no_tests(
        "\t Executed 0 tests, with 0 failures (0 unexpected) in 0.0 (0.0) seconds\n"
        "✔ Test run with 1 test in 0 suites passed after 0.001 seconds."
    )
    # macOS form
    assert not _no_tests("􁁛  Test run with 2 tests passed after 0.002 seconds.")


def test_no_tests_fail_patterns():
    assert _no_tests(
        "Build complete! (0.20s)\nerror: no tests found; create a target in the 'Tests' directory",
        "no_tests_fail_patterns",
    )
    assert not _no_tests(
        "\t Executed 1 test, with 1 failure (0 unexpected) in 0.002 (0.002) seconds",
        "no_tests_fail_patterns",
    )


def test_xctest_not_available_is_a_dependency_error():
    def matches(text: str) -> bool:
        return _matches_dep_error(text, _SWIFT["dep_error_phrases"], _SWIFT.get("dep_error_patterns", []))

    assert matches("error: XCTest not available")
    assert not matches("error: no tests found; create a target in the 'Tests' directory")


_NO_TEST_TARGET = (
    "import sys; print(\"error: no tests found; create a target in the 'Tests' directory\"); sys.exit(1)"
)
_ONE_FAILED = "import sys; print('Executed 1 test, with 1 failure'); sys.exit(1)"


def _run_stage(tmp_path: Path, stage: str, code: str, lang_cfg: dict):
    (tmp_path / "Package.swift").write_text("")
    project = Project(path=tmp_path, language="swift", primary_build_file="Package.swift")
    detection = DetectionResult(commands={stage: [
        StageCommand(command=[sys.executable, "-c", code], source="builtin"),
    ]})
    result = run_project(
        project=project,
        lang_cfg=lang_cfg,
        detection=detection,
        opts=OrchestratorOptions(),
        log_dir=tmp_path / "logs",
        repo_root=tmp_path,
    )
    return next(s for s in result.stages if s.stage == stage)


def test_no_test_target_is_skipped(tmp_path):
    stage = _run_stage(tmp_path, "tests", _NO_TEST_TARGET, _SWIFT)
    assert (stage.status, stage.reason) == ("skipped", "no_tests_found")


def test_coverage_with_no_test_target_is_skipped(tmp_path):
    stage = _run_stage(tmp_path, "coverage", _NO_TEST_TARGET, _SWIFT)
    assert (stage.status, stage.reason, stage.coverage_data) == ("skipped", "no_tests_found", None)


def test_failing_test_still_fails(tmp_path):
    assert _run_stage(tmp_path, "tests", _ONE_FAILED, _SWIFT).status == "fail"


def test_without_no_tests_fail_patterns_is_unchanged(tmp_path):
    cfg = copy.deepcopy(_SWIFT)
    del cfg["no_tests_fail_patterns"]
    assert _run_stage(tmp_path, "tests", _NO_TEST_TARGET, cfg).status == "fail"
