"""Tests for data-driven config -> command detection (Session 10).

Seam: detection.detect_commands(project, lang_cfg).  A language may declare
``config_commands`` rules in languages.toml:

    [[language.python.config_commands]]
    stage = "tests"
    files = ["pytest.ini"]              # any of these next to the build file
    pyproject_tables = ["tool.pytest"]  # or any of these tables in pyproject.toml
    command = "pytest"

A rule only fires for a stage that no script already covers, and only when the
project itself declares the tool (SPEC §3 step 3).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
from pre_llm_checks import load_languages

_STAGES = ["build", "lint", "tests", "coverage"]


def _cfg(*rules) -> dict:
    return {"stages": _STAGES, "config_commands": list(rules)}


_PYTEST = {
    "stage": "tests",
    "files": ["pytest.ini"],
    "pyproject_tables": ["tool.pytest"],
    "command": "pytest",
}
_RUFF = {
    "stage": "lint",
    "files": ["ruff.toml", ".ruff.toml"],
    "pyproject_tables": ["tool.ruff"],
    "command": "ruff check .",
}
_FLAKE8 = {"stage": "lint", "files": [".flake8"], "command": "flake8 ."}
_COVERAGE = {
    "stage": "coverage",
    "files": [".coveragerc"],
    "pyproject_tables": ["tool.coverage"],
    "command": "pytest --cov --cov-report=xml",
}


def _py(tmp_path: Path, **files: str) -> Project:
    """Create a python project folder; kwargs map file name -> content (keys may contain dots)."""
    (tmp_path / "pyproject.toml").write_text(files.pop("pyproject", "[project]\nname='x'\n"))
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    return Project(path=tmp_path, language="python", primary_build_file="pyproject.toml")


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def test_pytest_ini_adds_tests_command(tmp_path):
    proj = _py(tmp_path, **{"pytest.ini": "[pytest]\n"})
    r = detect_commands(proj, _cfg(_PYTEST))
    assert _argv(r, "tests") == [["pytest"]]
    assert r.commands["tests"][0].source == "config"


def test_pyproject_table_adds_tests_command(tmp_path):
    proj = _py(tmp_path, pyproject="[tool.pytest.ini_options]\naddopts='-q'\n")
    r = detect_commands(proj, _cfg(_PYTEST))
    assert _argv(r, "tests") == [["pytest"]]


def test_pyproject_without_tool_table_adds_nothing(tmp_path):
    proj = _py(tmp_path)
    r = detect_commands(proj, _cfg(_PYTEST, _RUFF))
    assert _argv(r, "tests") == [] and _argv(r, "lint") == []


def test_dev_dependency_alone_adds_nothing(tmp_path):
    proj = _py(tmp_path, pyproject="[project]\nname='x'\n[project.optional-dependencies]\ndev=['pytest','ruff']\n")
    r = detect_commands(proj, _cfg(_PYTEST, _RUFF))
    assert _argv(r, "tests") == [] and _argv(r, "lint") == []


def test_ruff_toml_and_pyproject_table(tmp_path):
    a = detect_commands(_py(tmp_path, **{"ruff.toml": "line-length = 88\n"}), _cfg(_RUFF))
    assert _argv(a, "lint") == [["ruff", "check", "."]]
    sub = tmp_path / "b"
    sub.mkdir()
    b = detect_commands(_py(sub, pyproject="[tool.ruff]\nline-length = 88\n"), _cfg(_RUFF))
    assert _argv(b, "lint") == [["ruff", "check", "."]]


def test_two_configured_linters_both_run_in_rule_order(tmp_path):
    proj = _py(tmp_path, **{"ruff.toml": ""})
    (tmp_path / ".flake8").write_text("[flake8]\n")
    r = detect_commands(proj, _cfg(_RUFF, _FLAKE8))
    assert _argv(r, "lint") == [["ruff", "check", "."], ["flake8", "."]]


def test_same_tool_configured_twice_runs_once(tmp_path):
    proj = _py(tmp_path, pyproject="[tool.pytest.ini_options]\n", **{"pytest.ini": "[pytest]\n"})
    r = detect_commands(proj, _cfg(_PYTEST))
    assert _argv(r, "tests") == [["pytest"]]


def test_coverage_rule(tmp_path):
    proj = _py(tmp_path)
    (tmp_path / ".coveragerc").write_text("[run]\n")
    r = detect_commands(proj, _cfg(_COVERAGE))
    assert _argv(r, "coverage") == [["pytest", "--cov", "--cov-report=xml"]]


def test_malformed_pyproject_does_not_crash(tmp_path):
    proj = _py(tmp_path, pyproject="this is [not toml")
    r = detect_commands(proj, _cfg(_PYTEST, _RUFF))
    assert _argv(r, "tests") == []


def test_no_pyproject_at_all_does_not_crash(tmp_path):
    proj = Project(path=tmp_path, language="python", primary_build_file="requirements.txt")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    r = detect_commands(proj, _cfg(_PYTEST, _RUFF))
    assert _argv(r, "tests") == [["pytest"]]


def test_script_wins_over_config_rule(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    proj = Project(path=tmp_path, language="javascript", primary_build_file="package.json")
    cfg = {
        "stages": _STAGES,
        "stage_names": {"tests": ["test"]},
        "config_commands": [_PYTEST],
    }
    r = detect_commands(proj, cfg)
    assert [c.source for c in r.commands["tests"]] == ["script:test"]


def test_language_without_config_commands_is_unchanged(tmp_path):
    proj = _py(tmp_path, **{"pytest.ini": "[pytest]\n"})
    r = detect_commands(proj, {"stages": _STAGES})
    assert all(not v for v in r.commands.values())


def test_real_languages_toml_python_rules(tmp_path):
    languages = load_languages()
    rules = languages["python"].get("config_commands", [])
    assert rules, "python needs config_commands in languages.toml"
    proj = _py(
        tmp_path,
        pyproject="[tool.pytest.ini_options]\n[tool.ruff]\n[tool.coverage.run]\n",
    )
    r = detect_commands(proj, languages["python"])
    assert _argv(r, "tests") == [["pytest"]]
    assert _argv(r, "lint") == [["ruff", "check", "."]]
    assert _argv(r, "coverage") == [["pytest", "--cov", "--cov-report=xml"]]
    assert _argv(r, "build") == []  # python has no build stage command
