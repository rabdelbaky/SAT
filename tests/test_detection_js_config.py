"""Tests for JavaScript/TypeScript config -> command detection (Session 11).

Uses the real languages.toml entry for javascript.  Tools are run through
``npx --no-install`` so nothing is ever downloaded; a project that does not
have the tool installed gets a normal failing/tool_not_installed result.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
from orchestrator import _declares_no_dependencies, _matches_dep_error
from pre_llm_checks import load_languages

_JS = load_languages()["javascript"]


def _proj(tmp_path: Path, files: dict[str, str], package_json: str = '{"name": "x"}') -> Project:
    (tmp_path / "package.json").write_text(package_json)
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    return Project(path=tmp_path, language="javascript", primary_build_file="package.json")


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def test_bare_package_json_detects_nothing(tmp_path):
    r = detect_commands(_proj(tmp_path, {}), _JS)
    assert all(not v for v in r.commands.values())


def test_dev_dependencies_alone_detect_nothing(tmp_path):
    pj = '{"name": "x", "devDependencies": {"eslint": "^8", "jest": "^29", "typescript": "^5"}}'
    r = detect_commands(_proj(tmp_path, {}, pj), _JS)
    assert all(not v for v in r.commands.values())


def test_eslint_config_adds_lint_command(tmp_path):
    for i, name in enumerate([".eslintrc.json", "eslint.config.js", "eslint.config.mjs"]):
        d = tmp_path / str(i)
        d.mkdir()
        r = detect_commands(_proj(d, {name: "{}"}), _JS)
        assert _argv(r, "lint") == [["npx", "--no-install", "eslint", "."]], name
        assert r.commands["lint"][0].source == "config"


def test_biome_config_adds_lint_command(tmp_path):
    r = detect_commands(_proj(tmp_path, {"biome.json": "{}"}), _JS)
    assert _argv(r, "lint") == [["npx", "--no-install", "biome", "check", "."]]


def test_jest_config_adds_tests_and_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, {"jest.config.js": "module.exports = {};"}), _JS)
    assert _argv(r, "tests") == [["npx", "--no-install", "jest"]]
    assert _argv(r, "coverage") == [
        ["npx", "--no-install", "jest", "--coverage", "--coverageReporters=json-summary"]
    ]


def test_vitest_config(tmp_path):
    r = detect_commands(_proj(tmp_path, {"vitest.config.ts": "export default {}"}), _JS)
    assert _argv(r, "tests") == [["npx", "--no-install", "vitest", "run"]]


def test_mocha_config(tmp_path):
    r = detect_commands(_proj(tmp_path, {".mocharc.json": "{}"}), _JS)
    assert _argv(r, "tests") == [["npx", "--no-install", "mocha"]]


def test_tsconfig_adds_build_typecheck(tmp_path):
    r = detect_commands(_proj(tmp_path, {"tsconfig.json": "{}"}), _JS)
    assert _argv(r, "build") == [["npx", "--no-install", "tsc", "--noEmit"]]


def test_script_beats_config_for_that_stage_only(tmp_path):
    pj = '{"name": "x", "scripts": {"test": "node --test"}}'
    r = detect_commands(_proj(tmp_path, {"jest.config.js": "", ".eslintrc.json": "{}"}, pj), _JS)
    assert _argv(r, "tests") == [["npm", "run", "test"]]  # script wins, jest rule ignored
    assert _argv(r, "lint") == [["npx", "--no-install", "eslint", "."]]  # no lint script -> config rule


def test_jest_key_in_package_json_adds_tests_and_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, {}, '{"name": "x", "jest": {}}'), _JS)
    assert _argv(r, "tests") == [["npx", "--no-install", "jest"]]
    assert _argv(r, "coverage") == [
        ["npx", "--no-install", "jest", "--coverage", "--coverageReporters=json-summary"]
    ]


def test_mocha_key_in_package_json_adds_tests(tmp_path):
    r = detect_commands(_proj(tmp_path, {}, '{"name": "x", "mocha": {}}'), _JS)
    assert _argv(r, "tests") == [["npx", "--no-install", "mocha"]]


def test_typecheck_script_is_a_build_command(tmp_path):
    pj = '{"name": "x", "scripts": {"typecheck": "tsc --noEmit"}}'
    r = detect_commands(_proj(tmp_path, {}, pj), _JS)
    assert _argv(r, "build") == [["npm", "run", "typecheck"]]


def test_real_languages_toml_has_no_javascript_config_files_table():
    assert "config_files" not in _JS


def _js_dep_missing(output: str) -> bool:
    return _matches_dep_error(
        output, _JS.get("dep_error_phrases", []), _JS.get("dep_error_patterns", [])
    )


@pytest.mark.parametrize(
    "output",
    [
        "Error: Cannot find module 'lodash'\nRequire stack:",
        "Cannot find module '@scope/pkg' from 'calc.test.js'",
        "error TS2307: Cannot find module 'react' or its corresponding type declarations.",
        "Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'lodash' imported from /a/b.mjs",
        "sh: eslint: command not found",
        "> x@1.0.0 lint\n> eslint .\n\nsh: 1: eslint: not found",
        "'eslint' is not recognized as an internal or external command,",
        'npm error npx canceled due to missing packages and no YES option: ["jest@29"]',
    ],
)
def test_missing_package_output_is_dependencies_missing(output):
    assert _js_dep_missing(output)


@pytest.mark.parametrize(
    "output",
    [
        "Error: Cannot find module './calcx.js'\nRequire stack:\n  code: 'MODULE_NOT_FOUND'",
        "Cannot find module '../lib/util' from 'calc.test.js'",
        "error TS2307: Cannot find module './mathx' or its corresponding type declarations.",
        "Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/repo/src/x.js' imported from /repo/a.mjs",
        "Error: Cannot find module 'C:\\repo\\missing.js'",
        "Cannot find module '@/components/Button'",
        "npm error Lifecycle script `test` failed with error:",
        "npm ERR! Test failed.  See above for more details.",
    ],
)
def test_code_bug_or_plain_failure_is_not_dependencies_missing(output):
    assert not _js_dep_missing(output)


def _declares_none(tmp_path: Path, package_json: str) -> bool:
    return _declares_no_dependencies(_proj(tmp_path, {}, package_json), _JS["dep_declared_keys"])


def test_empty_dependencies_declares_no_dependencies(tmp_path):
    assert _declares_none(tmp_path, '{"name": "x", "dependencies": {}}') is True


def test_dev_dependency_declares_dependencies(tmp_path):
    assert _declares_none(tmp_path, '{"name": "x", "devDependencies": {"jest": "^29"}}') is False


def test_invalid_package_json_is_not_treated_as_no_dependencies(tmp_path):
    assert _declares_none(tmp_path, '{"name": "x",') is False
