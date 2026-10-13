"""Tests for the discover_projects() public function.

Seam: discover_projects(root: Path, languages: dict) -> list[Project]

A Project has: .path (Path), .language (str), .build_files (list[str]),
               .primary_build_file (str), .tested (bool)

These tests are written red-first against the monorepo fixture described in
tests/fixtures/EXPECTED.md.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from discovery import discover_projects, Project
from pre_llm_checks import load_languages

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_MONOREPO = Path(__file__).parent / "fixtures" / "monorepo"
LANGUAGES = load_languages()


def _by_path(projects: list[Project], rel: str) -> Project:
    """Return the project whose path matches *rel* (relative to fixture root)."""
    target = FIXTURE_MONOREPO / rel if rel != "." else FIXTURE_MONOREPO
    for p in projects:
        if p.path.resolve() == target.resolve():
            return p
    paths = [str(p.path) for p in projects]
    raise AssertionError(f"No project at {rel!r}. Found: {paths}")


# ---------------------------------------------------------------------------
# Cycle 1: basic return type
# ---------------------------------------------------------------------------


def test_discover_projects_returns_list():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    assert isinstance(result, list)


def test_discover_projects_returns_project_instances():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    assert len(result) > 0
    for p in result:
        assert isinstance(p, Project), f"Expected Project, got {type(p)}"


# ---------------------------------------------------------------------------
# Cycle 2: total project count
# ---------------------------------------------------------------------------


def test_discover_projects_finds_five_projects():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    assert len(result) == 5, f"Expected 5 projects, got {len(result)}: " + ", ".join(
        str(p.path) for p in result
    )


# ---------------------------------------------------------------------------
# Cycle 3: skipped folders are never traversed
# ---------------------------------------------------------------------------


def test_node_modules_is_skipped():
    """package.json inside node_modules must NOT produce a project."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert "node_modules" not in p.path.parts, (
            f"Project from node_modules leaked through: {p.path}"
        )


def test_build_dir_is_skipped():
    """pyproject.toml inside build/ must NOT produce a project."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert "build" not in p.path.parts, (
            f"Project from build/ leaked through: {p.path}"
        )


def test_git_dir_is_skipped():
    """.git directory must NOT be traversed."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert ".git" not in p.path.parts, f"Project from .git leaked through: {p.path}"


# ---------------------------------------------------------------------------
# Cycle 4: root project is found
# ---------------------------------------------------------------------------


def test_root_javascript_project_found():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    root_proj = _by_path(result, ".")
    assert root_proj.language == "javascript"


def test_root_project_build_files_contains_package_json():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    root_proj = _by_path(result, ".")
    assert "package.json" in root_proj.build_files


# ---------------------------------------------------------------------------
# Cycle 5: sub-projects in packages/ are found separately from root
# ---------------------------------------------------------------------------


def test_packages_api_project_found():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    api = _by_path(result, "packages/api")
    assert api.language == "javascript"


def test_packages_ui_project_found():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    ui = _by_path(result, "packages/ui")
    assert ui.language == "javascript"


# ---------------------------------------------------------------------------
# Cycle 6: Go sub-project is found
# ---------------------------------------------------------------------------


def test_services_worker_go_project_found():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    worker = _by_path(result, "services/worker")
    assert worker.language == "go"


def test_services_worker_build_files_contains_go_mod():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    worker = _by_path(result, "services/worker")
    assert "go.mod" in worker.build_files


# ---------------------------------------------------------------------------
# Cycle 7: Python sub-project with two build files — one project, priority winner
# ---------------------------------------------------------------------------


def test_services_ml_python_project_found():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    ml = _by_path(result, "services/ml")
    assert ml.language == "python"


def test_services_ml_only_one_project_not_two():
    """Two Python build files in one folder must produce exactly ONE project."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    ml_projects = [
        p
        for p in result
        if p.language == "python"
        and (FIXTURE_MONOREPO / "services" / "ml") == p.path.resolve()
    ]
    assert len(ml_projects) == 1, (
        f"Expected 1 python project at services/ml, got {len(ml_projects)}"
    )


def test_services_ml_both_build_files_listed():
    """Both pyproject.toml and requirements.txt must appear in build_files."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    ml = _by_path(result, "services/ml")
    assert "pyproject.toml" in ml.build_files
    assert "requirements.txt" in ml.build_files


def test_services_ml_primary_build_file_is_pyproject_toml():
    """pyproject.toml has higher priority than requirements.txt."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    ml = _by_path(result, "services/ml")
    assert ml.primary_build_file == "pyproject.toml", (
        f"Expected primary_build_file='pyproject.toml', got {ml.primary_build_file!r}"
    )


# ---------------------------------------------------------------------------
# Cycle 8: tested flag matches languages.toml (python, javascript, java, kotlin, go)
# ---------------------------------------------------------------------------


def test_only_promoted_fixture_projects_are_tested():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert p.tested is (p.language in ("python", "javascript", "java", "kotlin", "go")), (
            f"Project {p.path} ({p.language}) has tested={p.tested!r}"
        )


# ---------------------------------------------------------------------------
# Cycle 9: empty folder returns empty list
# ---------------------------------------------------------------------------


def test_empty_folder_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        result = discover_projects(Path(tmp), LANGUAGES)
    assert result == []


# ---------------------------------------------------------------------------
# Cycle 10: folder with only skipped dirs returns empty list
# ---------------------------------------------------------------------------


def test_only_skipped_dirs_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "node_modules").mkdir()
        (root / "node_modules" / "package.json").write_text('{"name":"x"}')
        (root / ".git").mkdir()
        result = discover_projects(root, LANGUAGES)
    assert result == []


# ---------------------------------------------------------------------------
# Cycle 11: sub-project beats root for file ownership (no cross-language claim)
# ---------------------------------------------------------------------------


def test_sub_project_does_not_claim_parent_files():
    """packages/api project path must not equal the monorepo root path."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    root_proj = _by_path(result, ".")
    api_proj = _by_path(result, "packages/api")
    assert root_proj.path.resolve() != api_proj.path.resolve()


def test_javascript_project_does_not_claim_go_files():
    """The root JS project must be language='javascript', not 'go'."""
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    root_proj = _by_path(result, ".")
    assert root_proj.language == "javascript"
    # And the Go project is separate
    worker = _by_path(result, "services/worker")
    assert worker.language == "go"


# ---------------------------------------------------------------------------
# Cycle 12: Project dataclass fields
# ---------------------------------------------------------------------------


def test_project_has_path_attribute():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert hasattr(p, "path"), f"Project missing .path: {p}"
        assert isinstance(p.path, Path)


def test_project_has_language_attribute():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert hasattr(p, "language"), f"Project missing .language: {p}"
        assert isinstance(p.language, str)


def test_project_has_build_files_attribute():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert hasattr(p, "build_files"), f"Project missing .build_files: {p}"
        assert isinstance(p.build_files, list)
        assert len(p.build_files) >= 1


def test_project_has_primary_build_file_attribute():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert hasattr(p, "primary_build_file"), (
            f"Project missing .primary_build_file: {p}"
        )
        assert isinstance(p.primary_build_file, str)
        assert p.primary_build_file in p.build_files


def test_project_has_tested_attribute():
    result = discover_projects(FIXTURE_MONOREPO, LANGUAGES)
    for p in result:
        assert hasattr(p, "tested"), f"Project missing .tested: {p}"
        assert isinstance(p.tested, bool)
