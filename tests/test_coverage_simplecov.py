"""Tests for the SimpleCov reader and Ruby detection (Session 18).

SimpleCov writes coverage/.last_run.json after a passing run, holding its own
totals (the numbers it prints, after ``# :nocov:`` and other exclusions):

    {"result": {"line": 80.0, "branch": 50.0}}

Older SimpleCov writes ``{"result": {"covered_percent": 85.71}}``.
coverage/.resultset.json is raw per-line data before exclusions; it is not read.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import (
    _detect_format,
    parse_coverage_from_output,
    read_coverage_file,
    read_project_coverage,
)
from detection import DetectionResult, StageCommand, _config_rule_matches, detect_commands
from discovery import Project
from orchestrator import OrchestratorOptions, run_project
from pre_llm_checks import load_languages


def _last_run(tmp_path: Path, data) -> Path:
    d = tmp_path / "coverage"
    d.mkdir(exist_ok=True)
    p = d / ".last_run.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return p


def test_line_and_branch(tmp_path):
    r = read_coverage_file(_last_run(tmp_path, {"result": {"line": 80.0, "branch": 50.0}}))
    assert r is not None
    assert (r.line_pct, r.branch_pct, r.format) == (80.0, 50.0, "simplecov")


def test_no_branch_key_gives_none(tmp_path):
    r = read_coverage_file(_last_run(tmp_path, {"result": {"line": 80.0}}))
    assert r.line_pct == 80.0 and r.branch_pct is None


def test_old_simplecov_covered_percent(tmp_path):
    r = read_coverage_file(_last_run(tmp_path, {"result": {"covered_percent": 85.71}}))
    assert r.line_pct == 85.71


def test_unreadable_variants_return_none(tmp_path):
    variants = ['{"result": {}}', '{"result": "x"}', "[]", "not json",
                '{"result": {"line": true}}', '{"result": {"line": 120}}',
                '{"result": {"line": NaN}}']
    for i, content in enumerate(variants):
        d = tmp_path / str(i)
        d.mkdir()
        assert read_coverage_file(_last_run(d, content)) is None, content


def test_detect_format():
    assert _detect_format(Path(".last_run.json")) == "simplecov"
    assert _detect_format(Path(".resultset.json")) == "unknown"


def test_fresh_and_stale_through_project_reader(tmp_path):
    p = _last_run(tmp_path, {"result": {"line": 80.0}})
    start = time.time()
    os.utime(p, (start + 1, start + 1))
    data = read_project_coverage(tmp_path, ["coverage/.last_run.json"], start, [])
    assert [(r.format, r.line_pct) for r in data.results] == [("simplecov", 80.0)]
    os.utime(p, (start - 100, start - 100))
    data = read_project_coverage(tmp_path, ["coverage/.last_run.json"], start, [])
    assert data.results == [] and "coverage_stale" in data.warnings


def test_simplecov_console_output():
    assert parse_coverage_from_output("Line coverage: 4 / 5 (80.00%)\nBranch coverage: 0 / 2 (0.00%)") == 80.0
    assert parse_coverage_from_output("Branch coverage: 0 / 2 (0.00%)\nLine coverage: 4 / 5 (80.00%)") == 80.0
    assert parse_coverage_from_output("Line Coverage: 91.2% (12 / 14)") == 91.2
    text = "Coverage report generated for RSpec to /x/coverage. 12 / 14 LOC (85.71%) covered.\n"
    assert parse_coverage_from_output(text) == 85.71
    assert parse_coverage_from_output("Branch coverage: 0 / 2 (0.00%)") is None


# --- Ruby detection ---------------------------------------------------------------

_RUBY = load_languages()["ruby"]


def _proj(tmp_path: Path, gemfile: str = 'source "https://rubygems.org"\n', extra: dict[str, str] | None = None) -> Project:
    (tmp_path / "Gemfile").write_text(gemfile)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="ruby", primary_build_file="Gemfile")


def _argv(result, stage):
    return [c.command for c in result.commands.get(stage, [])]


def test_bare_gemfile_detects_nothing(tmp_path):
    r = detect_commands(_proj(tmp_path), _RUBY)
    assert all(not v for v in r.commands.values())


def test_gems_listed_without_config_detect_nothing(tmp_path):
    gemfile = 'source "https://rubygems.org"\ngem "rspec"\ngem "rubocop"\ngem "simplecov"\n'
    r = detect_commands(_proj(tmp_path, gemfile), _RUBY)
    assert all(not v for v in r.commands.values())


def test_rspec_and_rubocop_configs(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".rspec": "--color\n", ".rubocop.yml": "AllCops: {}\n"}), _RUBY)
    assert _argv(r, "tests") == [["bundle", "exec", "rspec"]]
    assert _argv(r, "lint") == [["bundle", "exec", "rubocop"]]


def test_standard_config_never_fixes(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".standard.yml": "fix: true\n"}), _RUBY)
    assert _argv(r, "lint") == [["bundle", "exec", "standardrb", "--no-fix"]]


def test_coverage_with_rspec_and_simplecov_in_gemfile_double_quotes(tmp_path):
    r = detect_commands(_proj(tmp_path, 'gem "simplecov", require: false\n', {".rspec": ""}), _RUBY)
    assert _argv(r, "coverage") == [["bundle", "exec", "rspec"]]


def test_coverage_with_rspec_and_simplecov_in_gemfile_single_quotes(tmp_path):
    r = detect_commands(_proj(tmp_path, "gem 'simplecov', require: false\n", {".rspec": ""}), _RUBY)
    assert _argv(r, "coverage") == [["bundle", "exec", "rspec"]]


def test_coverage_with_rspec_and_simplecov_file(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".rspec": "", ".simplecov": "SimpleCov.start\n"}), _RUBY)
    assert _argv(r, "coverage") == [["bundle", "exec", "rspec"]]


def test_no_coverage_without_rspec(tmp_path):
    # A minitest project: `bundle exec rspec` would fail on fine code.
    r = detect_commands(_proj(tmp_path, 'gem "simplecov"\n', {".simplecov": "SimpleCov.start\n"}), _RUBY)
    assert _argv(r, "coverage") == []


def test_simplecov_lcov_alone_is_not_simplecov(tmp_path):
    r = detect_commands(_proj(tmp_path, 'gem "simplecov-lcov"\n', {".rspec": ""}), _RUBY)
    assert _argv(r, "coverage") == []


def test_requires_files_rule_key(tmp_path):
    rule = {"requires_files": [".a"], "files": [".b"]}
    proj = _proj(tmp_path, extra={".b": ""})
    assert _config_rule_matches(proj, rule) is False
    (tmp_path / ".a").write_text("")
    assert _config_rule_matches(proj, rule) is True


def test_ruby_config_shape():
    assert "build" not in _RUBY["stages"]
    assert "stage_names" not in _RUBY and "config_files" not in _RUBY
    # most Ruby projects use system or user gems, so vendor/bundle must not be required
    assert _RUBY["dep_folders"] == []
    assert _RUBY["coverage_needs_tests"] is True
    assert _RUBY["coverage_files"] == ["coverage/.last_run.json"]


# --- No tests ---------------------------------------------------------------------


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def _no_tests(text: str) -> bool:
    return _any(_RUBY["no_tests_patterns"], text) and not _any(_RUBY["tests_ran_patterns"], text)


def test_no_tests_patterns():
    assert _no_tests("No examples found.\n\nFinished in 0.0 seconds\n0 examples, 0 failures")
    assert _no_tests("0 runs, 0 assertions, 0 failures, 0 errors, 0 skips")
    assert not _no_tests("1 example, 0 failures")
    assert not _no_tests("3 examples, 1 failure")
    assert not _no_tests("1 runs, 1 assertions, 0 failures, 0 errors, 0 skips")


def _run_coverage(tmp_path: Path, printed: str, lang_cfg: dict):
    (tmp_path / "Gemfile").write_text("")
    project = Project(path=tmp_path, language="ruby", primary_build_file="Gemfile")
    detection = DetectionResult(commands={"coverage": [
        StageCommand(command=[sys.executable, "-c", f"print({printed!r})"], source="config"),
    ]})
    result = run_project(
        project=project,
        lang_cfg=lang_cfg,
        detection=detection,
        opts=OrchestratorOptions(),
        log_dir=tmp_path / "logs",
        repo_root=tmp_path,
    )
    return next(s for s in result.stages if s.stage == "coverage")


def test_coverage_with_no_tests_is_skipped(tmp_path):
    stage = _run_coverage(tmp_path, "0 examples, 0 failures", _RUBY)
    assert (stage.status, stage.reason, stage.coverage_data) == ("skipped", "no_tests_found", None)


def test_coverage_with_tests_passes(tmp_path):
    assert _run_coverage(tmp_path, "1 example, 0 failures", _RUBY).status == "pass"


def test_coverage_without_coverage_needs_tests_is_unchanged(tmp_path):
    cfg = copy.deepcopy(_RUBY)
    del cfg["coverage_needs_tests"]
    assert _run_coverage(tmp_path, "0 examples, 0 failures", cfg).status == "pass"
