"""Tests for detection.py — tool and script detection (Session 5).

Seams under test
----------------
1. detect_commands(project, lang_cfg) -> DetectionResult
   Public seam: given a Project and its language config, return the commands
   that should run for each stage and the scripts that were skipped.

2. load_pre_llm_toml(path) -> PreLlmConfig
   Public seam: parse pre-llm.toml and return ignore list + overrides.

3. apply_overrides(result, override) -> DetectionResult
   Public seam: replace detected commands with override commands where specified.

All tests are written against the fixture files in tests/fixtures/.
No command is executed.  Tests verify return types and values only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import (
    DetectionResult,
    SkippedScript,
    StageCommand,
    apply_overrides,
    detect_commands,
    load_pre_llm_toml,
)
from discovery import Project
from pre_llm_checks import load_languages

# ---------------------------------------------------------------------------
# Fixtures paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
RISKY = FIXTURES / "risky-scripts"
DUPES = FIXTURES / "duplicate-scripts"
DEVDEPS = FIXTURES / "devdeps-only"
OVERRIDE_IGNORE = FIXTURES / "override-ignore"

LANGUAGES = load_languages()
JS_CFG = LANGUAGES["javascript"]


def _js_project(path: Path) -> Project:
    return Project(
        path=path,
        language="javascript",
        primary_build_file="package.json",
        build_files=["package.json"],
        tested=False,
    )


# ---------------------------------------------------------------------------
# Cycle 1: return type
# ---------------------------------------------------------------------------


def test_detect_commands_returns_detection_result():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    assert isinstance(result, DetectionResult)


def test_detection_result_has_commands():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    assert hasattr(result, "commands")
    assert isinstance(result.commands, dict)


def test_detection_result_has_skipped_scripts():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    assert hasattr(result, "skipped_scripts")
    assert isinstance(result.skipped_scripts, list)


# ---------------------------------------------------------------------------
# Cycle 2: StageCommand and SkippedScript types
# ---------------------------------------------------------------------------


def test_stage_command_has_required_fields():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    for stage, cmds in result.commands.items():
        for cmd in cmds:
            assert isinstance(cmd, StageCommand)
            assert hasattr(cmd, "command")
            assert isinstance(cmd.command, list)  # arg list
            assert hasattr(cmd, "source")
            assert isinstance(cmd.source, str)


def test_skipped_script_has_required_fields():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    for skip in result.skipped_scripts:
        assert isinstance(skip, SkippedScript)
        assert hasattr(skip, "name")
        assert isinstance(skip.name, str)
        assert hasattr(skip, "reason")
        assert isinstance(skip.reason, str)


# ---------------------------------------------------------------------------
# Cycle 3: risky-scripts — kept scripts
# ---------------------------------------------------------------------------


def test_risky_lint_script_is_kept():
    """'lint' script must be detected for the lint stage."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    lint_cmds = result.commands.get("lint", [])
    assert len(lint_cmds) >= 1, f"Expected lint command, got {lint_cmds}"


def test_risky_test_script_is_kept():
    """'test' script must be detected for the tests stage."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    test_cmds = result.commands.get("tests", [])
    assert len(test_cmds) >= 1, f"Expected tests command, got {test_cmds}"


def test_risky_lint_command_is_npm_run_lint():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    lint_cmds = result.commands.get("lint", [])
    commands = [c.command for c in lint_cmds]
    assert ["npm", "run", "lint"] in commands, f"Got {commands}"


def test_risky_test_command_is_npm_run_test():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    test_cmds = result.commands.get("tests", [])
    commands = [c.command for c in test_cmds]
    assert ["npm", "run", "test"] in commands, f"Got {commands}"


# ---------------------------------------------------------------------------
# Cycle 4: risky-scripts — skipped scripts
# ---------------------------------------------------------------------------


def test_risky_lint_fix_is_skipped():
    """'lint:fix' must be skipped because name ends ':fix'."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    names = [s.name for s in result.skipped_scripts]
    assert "lint:fix" in names, f"skipped_scripts names: {names}"


def test_risky_test_watch_is_skipped():
    """'test:watch' must be skipped because name ends ':watch'."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    names = [s.name for s in result.skipped_scripts]
    assert "test:watch" in names, f"skipped_scripts names: {names}"


def test_risky_dev_is_skipped():
    """'dev' must be skipped because it matches a skip name."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    names = [s.name for s in result.skipped_scripts]
    assert "dev" in names, f"skipped_scripts names: {names}"


def test_risky_format_is_skipped_for_write_flag():
    """'format' uses --write so must be skipped."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    names = [s.name for s in result.skipped_scripts]
    assert "format" in names, f"skipped_scripts names: {names}"


def test_risky_skipped_reasons_are_non_empty():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    for skip in result.skipped_scripts:
        assert skip.reason, f"Empty reason for skipped script {skip.name!r}"


def test_risky_lint_fix_skip_reason_mentions_fix():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    skip = next(s for s in result.skipped_scripts if s.name == "lint:fix")
    assert "fix" in skip.reason.lower(), f"Reason was {skip.reason!r}"


def test_risky_format_skip_reason_mentions_write():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    skip = next(s for s in result.skipped_scripts if s.name == "format")
    assert "write" in skip.reason.lower(), f"Reason was {skip.reason!r}"


# ---------------------------------------------------------------------------
# Cycle 5: risky-scripts — only lint and tests stages have commands
# ---------------------------------------------------------------------------


def test_risky_no_build_stage_commands():
    """No build script exists — build stage must be empty."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    build_cmds = result.commands.get("build", [])
    assert build_cmds == [], f"Expected no build commands, got {build_cmds}"


def test_risky_no_coverage_stage_commands():
    """No coverage script or config — coverage stage must be empty."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    cov_cmds = result.commands.get("coverage", [])
    assert cov_cmds == [], f"Expected no coverage commands, got {cov_cmds}"


# ---------------------------------------------------------------------------
# Cycle 6: duplicate-scripts — deduplication
# ---------------------------------------------------------------------------


def test_duplicate_test_commands_deduplicated():
    """'test' and 'test:ci' both run 'jest'; only one must survive."""
    proj = _js_project(DUPES)
    result = detect_commands(proj, JS_CFG)
    test_cmds = result.commands.get("tests", [])
    raw_commands = [c.command for c in test_cmds]
    # Count how many times the bare ["npm", "run", "test"] equivalent appears.
    # The dedup is on the underlying resolved command, not the npm run wrapper.
    # We check that the number of unique underlying commands ≤ total commands.
    # Specifically: jest appears twice; jest --ci appears once → 2 unique.
    assert len(test_cmds) == 2, (
        f"Expected 2 unique test commands (jest, jest --ci), got {len(test_cmds)}: "
        f"{raw_commands}"
    )


def test_duplicate_identical_commands_kept_once():
    """The same underlying command (jest) must appear exactly once."""
    proj = _js_project(DUPES)
    result = detect_commands(proj, JS_CFG)
    test_cmds = result.commands.get("tests", [])
    # Both 'test' and 'test:ci' map to 'jest'; one should be dropped.
    # We verify there's no duplication among the arg lists.
    seen: list[tuple] = []
    for cmd in test_cmds:
        key = tuple(cmd.command)
        assert key not in seen, (
            f"Duplicate command {cmd.command!r} found in tests stage"
        )
        seen.append(key)


def test_duplicate_different_args_both_kept():
    """'test' and 'test:coverage' map to different underlying commands; both kept.

    'test' → jest (underlying)
    'test:ci' → jest (same as test, deduplicated)
    'test:coverage' → jest --ci (different underlying, kept)
    """
    proj = _js_project(DUPES)
    result = detect_commands(proj, JS_CFG)
    test_cmds = result.commands.get("tests", [])
    # The npm-run wrapper form: ["npm", "run", "<script_name>"]
    script_names = [c.command[-1] for c in test_cmds if c.command[:2] == ["npm", "run"]]
    # We expect "test" (or "test:ci") and "test:coverage" to be present.
    # One of the "jest" scripts survives; "test:coverage" (jest --ci) also survives.
    has_coverage_script = any("coverage" in name for name in script_names)
    has_plain_script = any("coverage" not in name for name in script_names)
    assert has_coverage_script, f"test:coverage not found in {script_names}"
    assert has_plain_script, f"plain test script not found in {script_names}"


# ---------------------------------------------------------------------------
# Cycle 7: devdeps-only — nothing detected
# ---------------------------------------------------------------------------


def test_devdeps_only_no_commands_any_stage():
    """devDependencies-only project must produce no commands for any stage."""
    proj = _js_project(DEVDEPS)
    result = detect_commands(proj, JS_CFG)
    for stage, cmds in result.commands.items():
        assert cmds == [], (
            f"Stage {stage!r} unexpectedly has commands: {[c.command for c in cmds]}"
        )


def test_devdeps_only_no_skipped_scripts():
    """No scripts → nothing to skip."""
    proj = _js_project(DEVDEPS)
    result = detect_commands(proj, JS_CFG)
    assert result.skipped_scripts == [], (
        f"Expected no skipped scripts, got {result.skipped_scripts}"
    )


# ---------------------------------------------------------------------------
# Cycle 8: commands are arg lists, never shell strings
# ---------------------------------------------------------------------------


def test_commands_are_lists_not_strings():
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    for stage, cmds in result.commands.items():
        for cmd in cmds:
            assert isinstance(cmd.command, list), (
                f"Stage {stage!r}: command must be a list, got {type(cmd.command)}"
            )
            for arg in cmd.command:
                assert isinstance(arg, str), (
                    f"Each arg must be str, got {type(arg)!r} in {cmd.command!r}"
                )


# ---------------------------------------------------------------------------
# Cycle 9: source field
# ---------------------------------------------------------------------------


def test_script_source_format():
    """Source for script-detected commands must be 'script:<name>'."""
    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)
    for stage, cmds in result.commands.items():
        for cmd in cmds:
            if cmd.source != "override":
                assert cmd.source.startswith("script:"), (
                    f"Expected source to start with 'script:', got {cmd.source!r}"
                )


# ---------------------------------------------------------------------------
# Cycle 10: load_pre_llm_toml — valid file
# ---------------------------------------------------------------------------


def test_load_pre_llm_toml_returns_config():
    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    assert cfg is not None


def test_load_pre_llm_toml_has_ignore_list():
    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    assert hasattr(cfg, "ignore")
    assert isinstance(cfg.ignore, list)


def test_load_pre_llm_toml_ignore_contains_legacy():
    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    assert "legacy" in cfg.ignore, f"ignore={cfg.ignore!r}"


def test_load_pre_llm_toml_has_overrides():
    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    assert hasattr(cfg, "overrides")
    assert isinstance(cfg.overrides, list)


def test_load_pre_llm_toml_override_for_sub():
    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    assert len(cfg.overrides) == 1, f"Expected 1 override, got {cfg.overrides!r}"
    ov = cfg.overrides[0]
    assert ov.path == "sub", f"Expected path='sub', got {ov.path!r}"


def test_load_pre_llm_toml_override_tests_command():
    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    ov = cfg.overrides[0]
    assert hasattr(ov, "tests")
    assert ov.tests == "vitest run", f"Got {ov.tests!r}"


# ---------------------------------------------------------------------------
# Cycle 11: load_pre_llm_toml — missing file returns empty config
# ---------------------------------------------------------------------------


def test_load_pre_llm_toml_missing_returns_empty(tmp_path):
    cfg = load_pre_llm_toml(tmp_path / "pre-llm.toml")
    assert cfg.ignore == []
    assert cfg.overrides == []


# ---------------------------------------------------------------------------
# Cycle 12: load_pre_llm_toml — malformed TOML exits 2
# ---------------------------------------------------------------------------


def test_load_pre_llm_toml_malformed_raises(tmp_path):
    """Malformed TOML must raise PreLlmTomlError (caller converts to exit 2)."""
    from detection import PreLlmTomlError

    bad = tmp_path / "pre-llm.toml"
    bad.write_text("ignore = [[[not valid toml", encoding="utf-8")
    with pytest.raises(PreLlmTomlError):
        load_pre_llm_toml(bad)


# ---------------------------------------------------------------------------
# Cycle 13: load_pre_llm_toml — unknown top-level keys
# ---------------------------------------------------------------------------


def test_load_pre_llm_toml_unknown_key_raises(tmp_path):
    """Unknown top-level keys must raise PreLlmTomlError."""
    from detection import PreLlmTomlError

    bad = tmp_path / "pre-llm.toml"
    bad.write_text('unknown_key = "oops"\n', encoding="utf-8")
    with pytest.raises(PreLlmTomlError):
        load_pre_llm_toml(bad)


# ---------------------------------------------------------------------------
# Cycle 14: apply_overrides — override replaces detected command
# ---------------------------------------------------------------------------


def test_apply_overrides_replaces_tests_stage():
    """Override for 'tests' must replace the detected tests command."""
    from detection import ProjectOverride, PreLlmConfig

    proj = _js_project(OVERRIDE_IGNORE / "sub")
    result = detect_commands(proj, JS_CFG)

    # Confirm tests stage is detected from the script
    assert len(result.commands.get("tests", [])) >= 1

    # Build override
    override = ProjectOverride(path="sub", tests="vitest run")
    cfg = PreLlmConfig(ignore=[], overrides=[override])

    new_result = apply_overrides(result, override)

    test_cmds = new_result.commands.get("tests", [])
    assert len(test_cmds) == 1, f"Expected 1 tests command, got {test_cmds}"
    assert test_cmds[0].command == ["vitest", "run"], f"Got {test_cmds[0].command!r}"
    assert test_cmds[0].source == "override", f"Got source {test_cmds[0].source!r}"


def test_apply_overrides_does_not_touch_other_stages():
    """Override for 'tests' must not affect the 'lint' stage."""
    from detection import ProjectOverride

    proj = _js_project(OVERRIDE_IGNORE / "sub")
    result = detect_commands(proj, JS_CFG)
    lint_before = list(result.commands.get("lint", []))

    override = ProjectOverride(path="sub", tests="vitest run")
    new_result = apply_overrides(result, override)

    lint_after = new_result.commands.get("lint", [])
    assert [c.command for c in lint_after] == [c.command for c in lint_before], (
        "Lint stage was unexpectedly changed by tests override"
    )


# ---------------------------------------------------------------------------
# Cycle 15: ignore — legacy folder excluded from discovery
# ---------------------------------------------------------------------------


def test_ignore_excludes_legacy_from_discovery():
    """Folders listed in pre-llm.toml ignore must not produce projects."""
    from detection import load_pre_llm_toml
    from discovery import discover_projects

    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    projects = discover_projects(OVERRIDE_IGNORE, LANGUAGES, ignore=cfg.ignore)

    paths = [p.path.resolve() for p in projects]
    legacy_path = (OVERRIDE_IGNORE / "legacy").resolve()
    assert legacy_path not in paths, f"legacy/ should be ignored but found in {paths}"


def test_ignore_does_not_exclude_sub():
    """The 'sub' folder is NOT ignored and must be discovered."""
    from detection import load_pre_llm_toml
    from discovery import discover_projects

    cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")
    projects = discover_projects(OVERRIDE_IGNORE, LANGUAGES, ignore=cfg.ignore)

    paths = [p.path.resolve() for p in projects]
    sub_path = (OVERRIDE_IGNORE / "sub").resolve()
    assert sub_path in paths, (
        f"sub/ should be discovered but not found in {[str(p) for p in paths]}"
    )


# ---------------------------------------------------------------------------
# Cycle 16: override for non-existent path is a warning, not an error
# ---------------------------------------------------------------------------


def test_override_for_nonexistent_path_does_not_raise():
    """An override whose path matches no discovered project must not raise."""
    from detection import ProjectOverride, apply_overrides, DetectionResult

    proj = _js_project(RISKY)
    result = detect_commands(proj, JS_CFG)

    override = ProjectOverride(path="nonexistent-path", tests="echo hi")
    # Should not raise; the override simply has nothing to apply to
    new_result = apply_overrides(result, override)
    assert isinstance(new_result, DetectionResult)
