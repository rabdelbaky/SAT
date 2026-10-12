"""Tests for the SimpleCov reader and Ruby detection (Session 18).

SimpleCov writes coverage/.resultset.json:

    {"RSpec": {"coverage": {"/abs/calc.rb": {"lines": [1, 0, null, 2],
                                             "branches": {"[:if, 0, 3, 4, 3, 20]":
                                                 {"[:then, 1, 3, 4, 3, 10]": 1, "[:else, 2, 3, 4, 3, 20]": 0}}}},
               "timestamp": 1700000000}}

`null` lines are not relevant.  The old format stores the line array directly.
Several command names (RSpec + Minitest) are merged: a line is covered if any
command hit it.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_readers import parse_coverage_from_output, read_coverage_file, read_project_coverage
from detection import detect_commands
from discovery import Project
from pre_llm_checks import load_languages


def _resultset(tmp_path: Path, data) -> Path:
    d = tmp_path / "coverage"
    d.mkdir(exist_ok=True)
    p = d / ".resultset.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return p


def test_lines_across_files(tmp_path):
    p = _resultset(
        tmp_path,
        {"RSpec": {"coverage": {"/a/calc.rb": {"lines": [1, 0, None, 2]}, "/a/b.rb": {"lines": [1, 1]}}, "timestamp": 1}},
    )
    r = read_coverage_file(p)
    assert r is not None
    assert r.format == "simplecov"
    assert r.line_pct == 80.0  # (2 + 2) covered / (3 + 2) relevant
    assert r.branch_pct is None


def test_old_format_stores_line_array_directly(tmp_path):
    p = _resultset(tmp_path, {"RSpec": {"coverage": {"/a/calc.rb": [1, 0, None, 2]}, "timestamp": 1}})
    assert read_coverage_file(p).line_pct == round(2 / 3 * 100, 2)


def test_branch_coverage_when_present(tmp_path):
    branches = {"[:if, 0, 3, 4, 3, 20]": {"[:then, 1, 3, 4, 3, 10]": 1, "[:else, 2, 3, 4, 3, 20]": 0}}
    p = _resultset(tmp_path, {"RSpec": {"coverage": {"/a/c.rb": {"lines": [1], "branches": branches}}}})
    r = read_coverage_file(p)
    assert r.line_pct == 100.0 and r.branch_pct == 50.0


def test_several_command_names_are_merged_by_line(tmp_path):
    p = _resultset(
        tmp_path,
        {
            "RSpec": {"coverage": {"/a/c.rb": {"lines": [1, 0]}}},
            "Minitest": {"coverage": {"/a/c.rb": {"lines": [0, 1]}}},
        },
    )
    assert read_coverage_file(p).line_pct == 100.0


def test_unreadable_variants_return_none(tmp_path):
    for i, content in enumerate(["", "not json", "[]", "{}", '{"RSpec": {"coverage": {}}}',
                                 '{"RSpec": {"coverage": {"/a.rb": {"lines": [null, null]}}}}']):
        d = tmp_path / str(i)
        d.mkdir()
        assert read_coverage_file(_resultset(d, content)) is None, content


def test_fresh_and_stale_through_project_reader(tmp_path):
    p = _resultset(tmp_path, {"RSpec": {"coverage": {"/a.rb": {"lines": [1, 0]}}}})
    start = time.time()
    os.utime(p, (start + 1, start + 1))
    data = read_project_coverage(tmp_path, ["coverage/.resultset.json"], start, [])
    assert [(r.format, r.line_pct) for r in data.results] == [("simplecov", 50.0)]
    os.utime(p, (start - 100, start - 100))
    data = read_project_coverage(tmp_path, ["coverage/.resultset.json"], start, [])
    assert data.results == [] and "coverage_stale" in data.warnings


def test_simplecov_console_summary_is_parsed_from_output():
    text = "Coverage report generated for RSpec to /x/coverage. 12 / 14 LOC (85.71%) covered.\n"
    assert parse_coverage_from_output(text) == 85.71
    assert parse_coverage_from_output("Line Coverage: 91.2%") == 91.2


# --- Ruby detection ---------------------------------------------------------------

_RUBY = load_languages()["ruby"]


def _proj(tmp_path: Path, gemfile: str = 'source "https://rubygems.org"\n', extra: dict[str, str] | None = None) -> Project:
    (tmp_path / "Gemfile").write_text(gemfile)
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text)
    return Project(path=tmp_path, language="ruby", primary_build_file="Gemfile")


def _argv(result, stage):
    return [c.command for c in result.commands[stage]]


def test_bare_gemfile_detects_nothing(tmp_path):
    r = detect_commands(_proj(tmp_path), _RUBY)
    assert all(not v for v in r.commands.values())


def test_gems_listed_without_config_detect_nothing(tmp_path):
    gemfile = 'source "https://rubygems.org"\ngem "rspec"\ngem "rubocop"\n'
    r = detect_commands(_proj(tmp_path, gemfile), _RUBY)
    assert _argv(r, "tests") == [] and _argv(r, "lint") == []


def test_rspec_and_rubocop_configs(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".rspec": "--color\n", ".rubocop.yml": "AllCops: {}\n"}), _RUBY)
    assert _argv(r, "tests") == [["bundle", "exec", "rspec"]]
    assert _argv(r, "lint") == [["bundle", "exec", "rubocop"]]


def test_standard_config(tmp_path):
    r = detect_commands(_proj(tmp_path, extra={".standard.yml": "ruby_version: 3.2\n"}), _RUBY)
    assert _argv(r, "lint") == [["bundle", "exec", "standardrb"]]


def test_simplecov_in_gemfile_or_config_adds_coverage(tmp_path):
    r = detect_commands(_proj(tmp_path, 'gem "simplecov", require: false\n'), _RUBY)
    assert _argv(r, "coverage") == [["bundle", "exec", "rspec"]]
    d = tmp_path / "b"
    d.mkdir()
    r = detect_commands(_proj(d, extra={".simplecov": "SimpleCov.start\n"}), _RUBY)
    assert _argv(r, "coverage") == [["bundle", "exec", "rspec"]]


def test_ruby_has_no_build_stage_and_no_vendor_bundle_requirement():
    assert "build" not in _RUBY["stages"]
    # most Ruby projects use system or user gems, so vendor/bundle must not be required
    assert _RUBY["dep_folders"] == []
