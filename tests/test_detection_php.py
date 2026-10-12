"""Tests for PHP detection (Session 17).

PHP has no build stage.  Tools are project-local (`vendor/bin/...`), declared by
a config file next to composer.json, or by a composer script.  No built-ins.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
from pre_llm_checks import load_languages

_PHP = load_languages()["php"]


def _proj(tmp_path: Path, composer: str = '{"name": "x/y"}', extra: dict[str, str] | None = None) -> Project:
    (tmp_path / "composer.json").write_text(composer)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="php", primary_build_file="composer.json")


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def test_bare_composer_json_detects_nothing(tmp_path):
    r = detect_commands(_proj(tmp_path), _PHP)
    assert all(not v for v in r.commands.values())


def test_require_dev_alone_detects_nothing(tmp_path):
    composer = '{"require-dev": {"phpunit/phpunit": "^10", "squizlabs/php_codesniffer": "^3"}}'
    r = detect_commands(_proj(tmp_path, composer), _PHP)
    assert all(not v for v in r.commands.values())


def test_composer_scripts_are_run_through_composer(tmp_path):
    composer = '{"scripts": {"test": "phpunit", "lint": "phpcs", "fix": "phpcbf"}}'
    r = detect_commands(_proj(tmp_path, composer), _PHP)
    assert _argv(r, "tests") == [["composer", "test"]]
    assert _argv(r, "lint") == [["composer", "lint"]]


def test_phpunit_config_adds_tests_and_coverage(tmp_path):
    for i, name in enumerate(["phpunit.xml", "phpunit.xml.dist"]):
        d = tmp_path / str(i)
        d.mkdir()
        r = detect_commands(_proj(d, extra={name: "<phpunit/>"}), _PHP)
        assert _argv(r, "tests") == [["vendor/bin/phpunit"]], name
        assert _argv(r, "coverage") == [["vendor/bin/phpunit", "--coverage-clover", "clover.xml"]], name


def test_phpcs_phpstan_psalm_each_add_a_linter_in_rule_order(tmp_path):
    r = detect_commands(
        _proj(tmp_path, extra={"psalm.xml": "<psalm/>", "phpstan.neon": "parameters: {}", "phpcs.xml": "<ruleset/>"}),
        _PHP,
    )
    assert _argv(r, "lint") == [
        ["vendor/bin/phpcs"],
        ["vendor/bin/phpstan", "analyse"],
        ["vendor/bin/psalm"],
    ]


def test_php_cs_fixer_runs_read_only(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".php-cs-fixer.dist.php": "<?php"}), _PHP)
    assert _argv(r, "lint") == [["vendor/bin/php-cs-fixer", "fix", "--dry-run", "--diff"]]


def test_script_beats_config_for_that_stage_only(tmp_path):
    composer = '{"scripts": {"test": "phpunit"}}'
    r = detect_commands(_proj(tmp_path, composer, {"phpunit.xml": "<phpunit/>", "phpcs.xml": "<ruleset/>"}), _PHP)
    assert _argv(r, "tests") == [["composer", "test"]]
    assert _argv(r, "lint") == [["vendor/bin/phpcs"]]


def test_php_has_no_build_stage():
    assert "build" not in _PHP["stages"]
