"""Manual detection checks for Session 5.

Run:   python tests/manual_detection_check.py
Each check prints PASS or FAIL with a short reason.
Exit code: 0 if all pass, 1 if any fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection import (
    DetectionResult,
    PreLlmConfig,
    PreLlmTomlError,
    ProjectOverride,
    SkippedScript,
    StageCommand,
    apply_overrides,
    detect_commands,
    load_pre_llm_toml,
)
from discovery import Project, discover_projects
from pre_llm_checks import load_languages

FIXTURES = Path(__file__).parent / "fixtures"
RISKY = FIXTURES / "risky-scripts"
DUPES = FIXTURES / "duplicate-scripts"
DEVDEPS = FIXTURES / "devdeps-only"
OVERRIDE_IGNORE = FIXTURES / "override-ignore"

LANGUAGES = load_languages()
JS_CFG = LANGUAGES["javascript"]

_failures: list[str] = []


def check(name: str, passed: bool, reason: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    detail = f"  ({reason})" if reason else ""
    print(f"{status}  {name}{detail}")
    if not passed:
        _failures.append(name)


def _js_project(path: Path) -> Project:
    return Project(
        path=path,
        language="javascript",
        primary_build_file="package.json",
        build_files=["package.json"],
        tested=False,
    )


# ---------------------------------------------------------------------------
# Section A: risky-scripts
# ---------------------------------------------------------------------------

risky = detect_commands(_js_project(RISKY), JS_CFG)

check(
    "risky-scripts: returns DetectionResult",
    isinstance(risky, DetectionResult),
)

lint_cmds = risky.commands.get("lint", [])
check(
    "risky-scripts: lint stage has at least one command",
    len(lint_cmds) >= 1,
    f"got {[c.command for c in lint_cmds]}",
)

test_cmds = risky.commands.get("tests", [])
check(
    "risky-scripts: tests stage has at least one command",
    len(test_cmds) >= 1,
    f"got {[c.command for c in test_cmds]}",
)

check(
    "risky-scripts: lint command is npm run lint",
    any(c.command == ["npm", "run", "lint"] for c in lint_cmds),
    f"lint commands: {[c.command for c in lint_cmds]}",
)

check(
    "risky-scripts: test command is npm run test",
    any(c.command == ["npm", "run", "test"] for c in test_cmds),
    f"test commands: {[c.command for c in test_cmds]}",
)

check(
    "risky-scripts: no build commands",
    risky.commands.get("build", []) == [],
    f"got {[c.command for c in risky.commands.get('build', [])]}",
)

check(
    "risky-scripts: no coverage commands",
    risky.commands.get("coverage", []) == [],
    f"got {[c.command for c in risky.commands.get('coverage', [])]}",
)

skipped_names = [s.name for s in risky.skipped_scripts]

check(
    "risky-scripts: lint:fix is skipped",
    "lint:fix" in skipped_names,
    f"skipped names: {skipped_names}",
)

check(
    "risky-scripts: test:watch is skipped",
    "test:watch" in skipped_names,
    f"skipped names: {skipped_names}",
)

check(
    "risky-scripts: dev is skipped",
    "dev" in skipped_names,
    f"skipped names: {skipped_names}",
)

check(
    "risky-scripts: format is skipped (--write)",
    "format" in skipped_names,
    f"skipped names: {skipped_names}",
)

lint_fix_skip = next((s for s in risky.skipped_scripts if s.name == "lint:fix"), None)
check(
    "risky-scripts: lint:fix skip reason mentions 'fix'",
    lint_fix_skip is not None and "fix" in lint_fix_skip.reason.lower(),
    f"reason: {(lint_fix_skip.reason if lint_fix_skip else 'NOT FOUND')!r}",
)

format_skip = next((s for s in risky.skipped_scripts if s.name == "format"), None)
check(
    "risky-scripts: format skip reason mentions 'write'",
    format_skip is not None and "write" in format_skip.reason.lower(),
    f"reason: {(format_skip.reason if format_skip else 'NOT FOUND')!r}",
)

check_skip = next((s for s in risky.skipped_scripts if s.name == "check"), None)
check(
    "risky-scripts: check is skipped",
    check_skip is not None,
    f"skipped names: {skipped_names}",
)
check(
    "risky-scripts: check skip reason mentions '--fix'",
    check_skip is not None and "fix" in check_skip.reason.lower(),
    f"reason: {(check_skip.reason if check_skip else 'NOT FOUND')!r}",
)

check(
    "risky-scripts: commands are lists of strings",
    all(
        isinstance(c.command, list) and all(isinstance(a, str) for a in c.command)
        for cmds in risky.commands.values()
        for c in cmds
    ),
    "some command is not a list[str]",
)

check(
    "risky-scripts: script sources start with 'script:'",
    all(
        c.source.startswith("script:")
        for cmds in risky.commands.values()
        for c in cmds
        if c.source != "override"
    ),
    f"sources: {[c.source for cmds in risky.commands.values() for c in cmds]}",
)

# ---------------------------------------------------------------------------
# Section B: duplicate-scripts
# ---------------------------------------------------------------------------

dupes = detect_commands(_js_project(DUPES), JS_CFG)

dupe_test_cmds = dupes.commands.get("tests", [])
check(
    "duplicate-scripts: exactly 2 unique test commands",
    len(dupe_test_cmds) == 2,
    f"got {len(dupe_test_cmds)}: {[c.command for c in dupe_test_cmds]}",
)

dupe_keys = [tuple(c.command) for c in dupe_test_cmds]
check(
    "duplicate-scripts: no duplicate arg lists",
    len(dupe_keys) == len(set(dupe_keys)),
    f"got {dupe_keys}",
)

check(
    "duplicate-scripts: test:coverage (jest --ci) is among commands",
    any(
        c.command[-1] == "test:coverage"
        for c in dupe_test_cmds
        if c.command[:2] == ["npm", "run"]
    ),
    f"commands: {[c.command for c in dupe_test_cmds]}",
)

dupe_lint_cmds = dupes.commands.get("lint", [])
dupe_lint_keys = [tuple(c.command) for c in dupe_lint_cmds]
check(
    "duplicate-scripts: identical lint commands planned only once",
    len(dupe_lint_cmds) == 1,
    f"got {len(dupe_lint_cmds)}: {[c.command for c in dupe_lint_cmds]}",
)
check(
    "duplicate-scripts: no duplicate lint arg lists",
    len(dupe_lint_keys) == len(set(dupe_lint_keys)),
    f"got {dupe_lint_keys}",
)

# ---------------------------------------------------------------------------
# Section C: devdeps-only
# ---------------------------------------------------------------------------

devdeps = detect_commands(_js_project(DEVDEPS), JS_CFG)

check(
    "devdeps-only: no commands for any stage",
    all(cmds == [] for cmds in devdeps.commands.values()),
    f"commands: { {s: [c.command for c in cmds] for s, cmds in devdeps.commands.items() if cmds} }",
)

check(
    "devdeps-only: no skipped scripts",
    devdeps.skipped_scripts == [],
    f"skipped: {devdeps.skipped_scripts}",
)

# ---------------------------------------------------------------------------
# Section D: load_pre_llm_toml
# ---------------------------------------------------------------------------

cfg = load_pre_llm_toml(OVERRIDE_IGNORE / "pre-llm.toml")

check(
    "pre-llm.toml: returns PreLlmConfig",
    isinstance(cfg, PreLlmConfig),
    f"got {type(cfg)}",
)

check(
    "pre-llm.toml: ignore contains 'legacy'",
    "legacy" in cfg.ignore,
    f"ignore={cfg.ignore!r}",
)

check(
    "pre-llm.toml: has 1 override",
    len(cfg.overrides) == 1,
    f"got {cfg.overrides!r}",
)

ov = cfg.overrides[0] if cfg.overrides else None
check(
    "pre-llm.toml: override path is 'sub'",
    ov is not None and ov.path == "sub",
    f"got {(ov.path if ov else 'NO OVERRIDE')!r}",
)

check(
    "pre-llm.toml: override tests is 'vitest run'",
    ov is not None and ov.tests == "vitest run",
    f"got {(ov.tests if ov else 'NO OVERRIDE')!r}",
)

# Missing file
import tempfile, os

with tempfile.TemporaryDirectory() as tmp:
    empty_cfg = load_pre_llm_toml(Path(tmp) / "pre-llm.toml")
check(
    "pre-llm.toml: missing file returns empty config",
    empty_cfg.ignore == [] and empty_cfg.overrides == [],
    f"got {empty_cfg!r}",
)

# Malformed TOML
with tempfile.TemporaryDirectory() as tmp:
    bad_path = Path(tmp) / "pre-llm.toml"
    bad_path.write_text("ignore = [[[bad", encoding="utf-8")
    raised = False
    try:
        load_pre_llm_toml(bad_path)
    except PreLlmTomlError:
        raised = True
check(
    "pre-llm.toml: malformed TOML raises PreLlmTomlError",
    raised,
)

# Unknown key
with tempfile.TemporaryDirectory() as tmp:
    unk_path = Path(tmp) / "pre-llm.toml"
    unk_path.write_text('bad_key = "oops"\n', encoding="utf-8")
    raised = False
    try:
        load_pre_llm_toml(unk_path)
    except PreLlmTomlError:
        raised = True
check(
    "pre-llm.toml: unknown key raises PreLlmTomlError",
    raised,
)

# ---------------------------------------------------------------------------
# Section E: apply_overrides
# ---------------------------------------------------------------------------

sub_proj = _js_project(OVERRIDE_IGNORE / "sub")
sub_result = detect_commands(sub_proj, JS_CFG)
override = ProjectOverride(path="sub", tests="vitest run")
overridden = apply_overrides(sub_result, override)

ovr_test_cmds = overridden.commands.get("tests", [])
check(
    "apply_overrides: tests stage replaced with override",
    len(ovr_test_cmds) == 1 and ovr_test_cmds[0].command == ["vitest", "run"],
    f"got {[c.command for c in ovr_test_cmds]}",
)

check(
    "apply_overrides: overridden command source is 'override'",
    len(ovr_test_cmds) == 1 and ovr_test_cmds[0].source == "override",
    f"got source {(ovr_test_cmds[0].source if ovr_test_cmds else 'NONE')!r}",
)

lint_before = [c.command for c in sub_result.commands.get("lint", [])]
lint_after = [c.command for c in overridden.commands.get("lint", [])]
check(
    "apply_overrides: lint stage unchanged by tests override",
    lint_before == lint_after,
    f"before={lint_before!r} after={lint_after!r}",
)

# ---------------------------------------------------------------------------
# Section F: ignore in discover_projects
# ---------------------------------------------------------------------------

projects_with_ignore = discover_projects(OVERRIDE_IGNORE, LANGUAGES, ignore=cfg.ignore)
project_paths = [p.path.resolve() for p in projects_with_ignore]

check(
    "ignore: legacy/ excluded from discovery",
    (OVERRIDE_IGNORE / "legacy").resolve() not in project_paths,
    f"found: {[str(p) for p in project_paths]}",
)

check(
    "ignore: sub/ still discovered",
    (OVERRIDE_IGNORE / "sub").resolve() in project_paths,
    f"found: {[str(p) for p in project_paths]}",
)

check(
    "ignore: root project still discovered",
    OVERRIDE_IGNORE.resolve() in project_paths,
    f"found: {[str(p) for p in project_paths]}",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
