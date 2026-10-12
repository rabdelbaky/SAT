"""Tests for JavaScript/TypeScript config -> command detection (Session 11).

Uses the real languages.toml entry for javascript.  Tools are run through
``npx --no-install`` so nothing is ever downloaded; a project that does not
have the tool installed gets a normal failing/tool_not_installed result.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import detect_commands
from discovery import Project
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


def test_dep_error_phrases_do_not_swallow_real_failures():
    # npm <= 10 prints "npm ERR!" for any failing script; matching it would turn
    # a genuine test/lint/build failure into dependencies_missing.
    phrases = _JS["dep_error_phrases"]
    assert not any("npm ERR" in p for p in phrases)
    assert "Cannot find module" in phrases and "MODULE_NOT_FOUND" in phrases
