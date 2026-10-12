"""Tests for Swift detection and discovery (Session 19).

- `swift build` / `swift test` are SwiftPM built-ins; nothing else is.
- swiftlint / swiftformat run only when the project declares them with a config
  file, and swiftformat only in its read-only `--lint` form.
- SwiftPM puts dependency checkouts (each with its own Package.swift) under
  `.build/`, which must not be discovered as projects.
- Coverage is not supported for Swift in v1: there is no coverage command.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project, discover_projects
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


def test_bare_package_gets_build_and_tests_only(tmp_path):
    r = detect_commands(_proj(tmp_path), _SWIFT)
    assert _argv(r, "build") == [["swift", "build"]]
    assert _argv(r, "tests") == [["swift", "test"]]
    assert _argv(r, "lint") == []
    assert _argv(r, "coverage") == []


def test_swiftlint_config_adds_lint(tmp_path):
    for i, name in enumerate([".swiftlint.yml", ".swiftlint.yaml"]):
        d = tmp_path / str(i)
        d.mkdir()
        r = detect_commands(_proj(d, {name: "disabled_rules: []"}), _SWIFT)
        assert _argv(r, "lint") == [["swiftlint"]], name
        assert r.commands["lint"][0].source == "config"


def test_swiftformat_runs_read_only(tmp_path):
    r = detect_commands(_proj(tmp_path, {".swiftformat": "--indent 4"}), _SWIFT)
    assert _argv(r, "lint") == [["swiftformat", "--lint", "."]]


def test_both_configured_run_in_rule_order(tmp_path):
    r = detect_commands(_proj(tmp_path, {".swiftformat": "", ".swiftlint.yml": ""}), _SWIFT)
    assert _argv(r, "lint") == [["swiftlint"], ["swiftformat", "--lint", "."]]


def test_dot_build_checkouts_are_not_projects(tmp_path):
    (tmp_path / "Package.swift").write_text("")
    dep = tmp_path / ".build" / "checkouts" / "some-dep"
    dep.mkdir(parents=True)
    (dep / "Package.swift").write_text("")
    found = [p.path for p in discover_projects(tmp_path, _LANGS) if p.language == "swift"]
    assert found == [tmp_path]
