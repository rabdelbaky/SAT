"""Tests for resolving project-relative executables (Session 17).

PHP tools live in the project (`vendor/bin/phpunit`) and Ruby/others use
`./bin/...`.  A relative path with a separator must be resolved against the
project folder (cwd given to the runner), not against the tool's own working
directory, otherwise every such tool is reported tool_not_installed.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from runner import resolve_executable

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses an executable bit")


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@posix_only
def test_vendor_bin_path_resolves_against_project_folder(tmp_path):
    tool = _exe(tmp_path / "vendor" / "bin" / "phpunit")
    assert resolve_executable(["vendor/bin/phpunit", "--colors=never"], tmp_path) == [
        str(tool),
        "--colors=never",
    ]


@posix_only
def test_dot_slash_path_resolves_against_project_folder(tmp_path):
    tool = _exe(tmp_path / "bin" / "rails")
    assert resolve_executable(["./bin/rails", "test"], tmp_path) == [str(tool), "test"]


@posix_only
def test_resolution_does_not_depend_on_process_cwd(tmp_path):
    tool = _exe(tmp_path / "vendor" / "bin" / "phpcs")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    old = os.getcwd()
    os.chdir(elsewhere)
    try:
        assert resolve_executable(["vendor/bin/phpcs"], tmp_path) == [str(tool)]
    finally:
        os.chdir(old)


def test_missing_relative_executable_is_none(tmp_path):
    assert resolve_executable(["vendor/bin/phpunit"], tmp_path) is None


def test_absolute_path_still_works(tmp_path):
    assert resolve_executable([sys.executable, "-V"], tmp_path) == [sys.executable, "-V"] or (
        resolve_executable([sys.executable, "-V"], tmp_path)[1:] == ["-V"]
    )


def test_bare_name_still_uses_path_lookup(tmp_path):
    name = "cmd" if sys.platform == "win32" else "sh"  # always on PATH
    resolved = resolve_executable([name, "-V"], tmp_path)
    assert resolved is not None and resolved[1:] == ["-V"]


def test_relative_path_to_a_directory_is_not_an_executable(tmp_path):
    (tmp_path / "vendor" / "bin" / "phpunit").mkdir(parents=True)
    assert resolve_executable(["vendor/bin/phpunit"], tmp_path) is None
