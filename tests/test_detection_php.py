"""Tests for PHP detection (Session 17).

PHP has no build stage.  Tools are project-local (`vendor/bin/...`), declared by
a config file next to composer.json, or by a composer script.  No built-ins.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
from orchestrator import _declares_no_dependencies
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


_TESTS_ARGV = ["vendor/bin/phpunit", "--no-coverage", "--do-not-cache-result"]
_COVERAGE_ARGV = ["vendor/bin/phpunit", "--do-not-cache-result", "--coverage-clover", "clover.xml"]


def test_phpunit_config_adds_tests_and_coverage(tmp_path):
    for i, name in enumerate(["phpunit.xml", "phpunit.xml.dist", "phpunit.dist.xml"]):
        d = tmp_path / str(i)
        d.mkdir()
        r = detect_commands(_proj(d, extra={name: "<phpunit/>"}), _PHP)
        assert _argv(r, "tests") == [_TESTS_ARGV], name
        assert _argv(r, "coverage") == [_COVERAGE_ARGV], name


def test_dot_phpcs_xml_dist_adds_phpcs(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".phpcs.xml.dist": "<ruleset/>"}), _PHP)
    assert _argv(r, "lint") == [["vendor/bin/phpcs"]]


def test_phpstan_dist_neon_adds_phpstan(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={"phpstan.dist.neon": "parameters: {}"}), _PHP)
    assert _argv(r, "lint") == [["vendor/bin/phpstan", "analyse"]]


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
    assert _argv(r, "lint") == [["vendor/bin/php-cs-fixer", "fix", "--dry-run", "--diff", "--using-cache=no"]]


def test_script_beats_config_for_that_stage_only(tmp_path):
    composer = '{"scripts": {"test": "phpunit"}}'
    r = detect_commands(_proj(tmp_path, composer, {"phpunit.xml": "<phpunit/>", "phpcs.xml": "<ruleset/>"}), _PHP)
    assert _argv(r, "tests") == [["composer", "test"]]
    assert _argv(r, "lint") == [["vendor/bin/phpcs"]]


def test_php_has_no_build_stage():
    assert "build" not in _PHP["stages"]


def test_php_has_no_config_files_table():
    assert "config_files" not in _PHP


# --- composer scripts that run a fixer ---------------------------------------

def _scripts(tmp_path: Path, scripts: dict) -> Project:
    return _proj(tmp_path, json.dumps({"name": "x/y", "scripts": scripts}))


_FIXER_SCRIPTS = [
    {"lint": "phpcbf"},
    {"lint": "vendor/bin/php-cs-fixer fix"},
    {"lint": "pint"},
    {"lint": "rector process"},
    {"lint": "psalm --alter --issues=all"},
    {"lint": ["phpcs", "phpcbf"]},
    {"lint": ["phpcs", "@cs-fix"], "cs-fix": "phpcbf"},
    {"lint": "@php vendor/bin/phpcbf"},
]


@pytest.mark.parametrize("scripts", _FIXER_SCRIPTS, ids=lambda s: json.dumps(s["lint"]))
def test_fixer_script_is_skipped(tmp_path, scripts):
    r = detect_commands(_scripts(tmp_path, scripts), _PHP)
    assert _argv(r, "lint") == []
    reasons = {s.name: s.reason for s in r.skipped_scripts}
    assert reasons.get("lint") == "command runs a fixer"


_READ_ONLY_SCRIPTS = [
    "php-cs-fixer fix --dry-run --diff",
    "pint --test",
    "rector process --dry-run",
    "phpcs",
    ["phpcs", "@php -l src/a.php"],
]


@pytest.mark.parametrize("value", _READ_ONLY_SCRIPTS, ids=json.dumps)
def test_read_only_script_is_not_skipped(tmp_path, value):
    r = detect_commands(_scripts(tmp_path, {"lint": value}), _PHP)
    assert _argv(r, "lint") == [["composer", "lint"]]
    assert r.skipped_scripts == []


def test_script_reference_cycle_terminates_and_is_not_skipped(tmp_path):
    r = detect_commands(_scripts(tmp_path, {"lint": "@a", "a": "@lint"}), _PHP)
    assert _argv(r, "lint") == [["composer", "lint"]]
    assert r.skipped_scripts == []


@pytest.mark.parametrize("text", ["phpstan analyse", "php artisan test", "blueprint build"])
def test_fixer_patterns_leave_ordinary_commands_alone(text):
    assert not any(re.search(p, text) for p in _PHP["fixer_patterns"])


# --- vendor/ expected only when composer.json declares packages ----------------

@pytest.mark.parametrize(
    "composer, expected",
    [
        ({"name": "x", "scripts": {"test": "php t.php"}}, True),
        ({"require-dev": {"phpunit/phpunit": "^11"}}, False),
        ({"autoload": {"psr-4": {"App\\": "src/"}}}, False),
    ],
)
def test_declares_no_dependencies(tmp_path, composer, expected):
    project = _proj(tmp_path, json.dumps(composer))
    assert _declares_no_dependencies(project, _PHP["dep_declared_keys"]) is expected


# --- no-tests patterns ----------------------------------------------------------

def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def _no_tests(text: str) -> bool:
    return _any(_PHP["no_tests_patterns"], text) and not _any(_PHP["tests_ran_patterns"], text)


_HEADER = "PHPUnit 11.5.0 by Sebastian Bergmann and contributors.\n\nRuntime:       PHP 8.3.0\n\n"


def test_no_tests_executed_is_no_tests():
    assert _no_tests(_HEADER + "Time: 00:00.001, Memory: 8.00 MB\n\nNo tests executed!\n")


def test_ok_is_not_no_tests():
    assert not _no_tests(_HEADER + ".  1 / 1 (100%)\n\nTime: 00:00.010, Memory: 8.00 MB\n\nOK (1 test, 1 assertion)\n")


def test_ok_with_issues_is_not_no_tests():
    assert not _no_tests(
        _HEADER + "W  1 / 1 (100%)\n\nOK, but there were issues!\nTests: 1, Assertions: 1, PHPUnit Warnings: 1.\n"
    )


def test_failures_is_not_no_tests():
    assert not _no_tests(_HEADER + "F  1 / 1 (100%)\n\nFAILURES!\nTests: 1, Assertions: 1, Failures: 1.\n")
