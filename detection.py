"""Tool and script detection for Pre-LLM Checks (Session 5).

Public API
----------
detect_commands(project, lang_cfg) -> DetectionResult
    Given a discovered Project and its language config from languages.toml,
    return the commands to run for each stage and the scripts that were skipped.

load_pre_llm_toml(path) -> PreLlmConfig
    Parse the optional pre-llm.toml at *path*.  Returns an empty config if the
    file does not exist.  Raises PreLlmTomlError on malformed TOML or unknown
    keys.

apply_overrides(result, override) -> DetectionResult
    Replace detected commands in *result* with override commands from *override*.
    Stages not mentioned in *override* are left unchanged.

Rules (SPEC §3 steps 3–4, §4):
- A tool counts only if project-defined: script in build file, plugin in build
  file, config file next to it, built-in Maven/Gradle phase, or pre-llm.toml
  override.  A package only in devDependencies with no script and no config is
  ignored.
- Match scripts to stages by exact name and prefix (lint and lint:types both
  count as lint).
- Skip names ending :fix :watch :dev :serve :e2e :docker :deploy and any
  command using --fix or --write.  Record each skipped script with its reason.
- Identical commands (same resolved argv) run once.  Different args are
  different commands (jest vs jest --ci).
- Stage names, config files, and built-in phases come from languages.toml.
- Commands are stored as argument lists, never run through a shell.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import configparser
import fnmatch
import json
import re
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from discovery import solution_projects


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class StageCommand:
    """One command to execute for a stage."""

    command: list[str]  # argument list — never a shell string
    source: str  # e.g. "script:test", "builtin", "config", "override"


@dataclass
class SkippedScript:
    """A script that was excluded from detection with its reason."""

    name: str
    reason: str


@dataclass
class DetectionResult:
    """All detection output for one project."""

    commands: dict[str, list[StageCommand]] = field(default_factory=dict)
    skipped_scripts: list[SkippedScript] = field(default_factory=list)


# ---------------------------------------------------------------------------
# pre-llm.toml types
# ---------------------------------------------------------------------------


class PreLlmTomlError(Exception):
    """Raised on malformed pre-llm.toml or unknown keys."""


@dataclass
class ProjectOverride:
    """Per-project command overrides from pre-llm.toml."""

    path: str
    build: Optional[str] = None
    lint: Optional[str] = None
    tests: Optional[str] = None
    coverage: Optional[str] = None


@dataclass
class PreLlmConfig:
    """Parsed content of pre-llm.toml."""

    ignore: list[str] = field(default_factory=list)
    overrides: list[ProjectOverride] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Skip rules (SPEC §3 step 4)
# ---------------------------------------------------------------------------

# Script name suffixes that disqualify a script entirely.
_SKIP_SUFFIXES: tuple[str, ...] = (
    ":fix",
    ":watch",
    ":dev",
    ":serve",
    ":e2e",
    ":docker",
    ":deploy",
)

# Exact script names that are also skipped (bare names without a colon prefix).
_SKIP_EXACT_NAMES: frozenset[str] = frozenset({"dev", "serve", "deploy", "docker"})

# CLI flags in a command that disqualify it regardless of script name.
_SKIP_FLAGS: tuple[str, ...] = ("--fix", "--write")


def _skip_reason(
    name: str, command: str, fixer_patterns: list[str] | None = None
) -> str | None:
    """Return a skip reason string if this script should be skipped, else None.

    *fixer_patterns* (languages.toml ``fixer_patterns``) are regexes for tools
    that rewrite code without a --fix/--write flag (e.g. phpcbf); a match skips
    the script.  A pattern that is not a valid regex is ignored.
    """
    # Check exact name matches first
    if name in _SKIP_EXACT_NAMES:
        return f"name is '{name}' (skip name)"

    # Check name suffix
    for suffix in _SKIP_SUFFIXES:
        if name.endswith(suffix):
            return f"name ends '{suffix}'"

    # Check command flags
    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    for flag in _SKIP_FLAGS:
        if flag in args:
            return f"command uses '{flag}'"

    # Check tools that rewrite code by default
    for pattern in fixer_patterns or []:
        try:
            if re.search(pattern, command):
                return "command runs a fixer"
        except re.error:
            continue

    return None


# ---------------------------------------------------------------------------
# Stage matching
# ---------------------------------------------------------------------------


def _stage_for_script(
    script_name: str, stage_names: dict[str, list[str]]
) -> str | None:
    """Return the stage name for *script_name*, or None if it matches no stage.

    Matching rules (SPEC §3 step 4):
    - Exact match: "lint" matches the lint stage.
    - Prefix match: "lint:types" matches the lint stage (starts with "lint").
    - The script name is compared against each entry in stage_names[stage].
    """
    for stage, patterns in stage_names.items():
        for pattern in patterns:
            if script_name == pattern:
                return stage
            if script_name.startswith(pattern + ":"):
                return stage
    return None


# ---------------------------------------------------------------------------
# npm/yarn/pnpm script runner detection
# ---------------------------------------------------------------------------


def _npm_runner_for_project(project_path: Path) -> list[str]:
    """Return the npm-compatible runner prefix for this project.

    Checks for yarn.lock, pnpm-lock.yaml, bun.lockb in order; falls back to
    npm.  Returns e.g. ["npm", "run"] or ["yarn"] or ["pnpm", "run"].
    """
    if (project_path / "yarn.lock").exists():
        return ["yarn"]
    if (project_path / "pnpm-lock.yaml").exists():
        return ["pnpm", "run"]
    if (project_path / "bun.lockb").exists():
        return ["bun", "run"]
    return ["npm", "run"]


# ---------------------------------------------------------------------------
# Config-file-based detection
# ---------------------------------------------------------------------------


def _has_config_file(project_path: Path, config_patterns: list[str]) -> bool:
    """Return True if any file in *project_path* matches a pattern in *config_patterns*."""
    try:
        entries = [e.name for e in project_path.iterdir() if e.is_file()]
    except PermissionError:
        return False
    for pattern in config_patterns:
        for name in entries:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


def _pyproject_has_table(project_path: Path, dotted: str) -> bool:
    """Return True if pyproject.toml next to the build file has table *dotted*."""
    try:
        with open(project_path / "pyproject.toml", "rb") as fh:
            node = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _ini_has_section(project_path: Path, file_name: str, section: str) -> bool:
    """Return True if INI-style *file_name* next to the build file has *section*.

    Read-only.  A missing or unreadable/invalid file counts as no section.
    """
    path = project_path / file_name
    if not path.is_file():
        return False
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path, encoding="utf-8") as fh:
            parser.read_file(fh)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return False
    return parser.has_section(section)


def _package_json_has_key(project_path: Path, key: str) -> bool:
    """Return True if package.json next to the build file has top-level *key*.

    Read-only.  A missing or invalid package.json counts as no key.
    """
    try:
        with open(project_path / "package.json", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and key in data


_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def _build_file_text(project: "Project") -> str:
    """Return the project's primary build file without comments ("" if unreadable).

    A plugin that is only mentioned in a comment (or commented out) is not
    declared.  pom.xml: <!-- --> comments.  Gradle scripts: /* */ and //
    comments (a // inside a URL string cuts the rest of that line, which
    never holds a plugin id).  A .sln / .slnx: the solution text plus each
    .csproj it lists (XML comments removed; unreadable files skipped), since
    packages such as coverlet.collector are referenced there.
    """
    build_file = project.path / project.primary_build_file
    if project.primary_build_file.endswith((".sln", ".slnx")):
        try:
            parts = [build_file.read_text(encoding="utf-8-sig", errors="replace")]
        except OSError:
            return ""
        for csproj in sorted(solution_projects(build_file)):
            try:
                text = csproj.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            parts.append(_XML_COMMENT.sub("", text))
        return "\n".join(parts)
    try:
        text = build_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if project.primary_build_file.endswith(".xml"):
        return _XML_COMMENT.sub("", text)
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _config_rule_matches(project: "Project", rule: dict) -> bool:
    """Return True if the project declares the tool a config_commands rule names.

    Optional ``build_files`` limits a rule to projects whose primary build file
    is in the list (e.g. Maven-only rules).  The tool is then declared by any of:
    ``files`` next to the build file, ``pyproject_tables`` in pyproject.toml,
    ``ini_sections``, ``package_json_keys``, or ``build_file_contains`` (a
    plugin name inside the primary build file).
    """
    applies_to = rule.get("build_files")
    if applies_to and project.primary_build_file not in applies_to:
        return False
    project_path = project.path
    files = rule.get("files", [])
    if files and _has_config_file(project_path, files):
        return True
    if any(
        _pyproject_has_table(project_path, t) for t in rule.get("pyproject_tables", [])
    ):
        return True
    for pair in rule.get("ini_sections", []):
        if not (
            isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(x, str) for x in pair)
        ):
            continue
        if _ini_has_section(project_path, pair[0], pair[1]):
            return True
    if any(
        isinstance(key, str) and _package_json_has_key(project_path, key)
        for key in rule.get("package_json_keys", [])
    ):
        return True
    needles = rule.get("build_file_contains", [])
    if needles:
        text = _build_file_text(project)
        return any(n in text for n in needles)
    return False


# ---------------------------------------------------------------------------
# package.json script parsing
# ---------------------------------------------------------------------------


def _load_package_scripts(project_path: Path) -> dict[str, str]:
    """Return the scripts dict from package.json, or {} on any error."""
    pkg = project_path / "package.json"
    if not pkg.exists():
        return {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict):
            return {
                k: v
                for k, v in scripts.items()
                if isinstance(k, str) and isinstance(v, str)
            }
    except (json.JSONDecodeError, OSError):
        pass
    return {}


# ---------------------------------------------------------------------------
# pyproject.toml / composer.json / Cargo.toml script parsing
# ---------------------------------------------------------------------------


def _load_pyproject_scripts(project_path: Path) -> dict[str, str]:
    """Return [tool.hatch.envs.*.scripts] or [tool.taskipy.tasks] etc.

    For simplicity in v1: return only the standard poetry scripts section
    [tool.poetry.scripts] (these are entry points, not run scripts).
    The main detection path for Python is config files and built-in phases,
    not scripts.  Return empty for now.
    """
    return {}


def _load_composer_scripts(project_path: Path) -> dict[str, str]:
    """Return composer.json scripts section."""
    composer = project_path / "composer.json"
    if not composer.exists():
        return {}
    try:
        data = json.loads(composer.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict):
            # Composer script values can be strings or arrays; normalise to str.
            result = {}
            for k, v in scripts.items():
                if isinstance(k, str):
                    if isinstance(v, str):
                        result[k] = v
                    elif isinstance(v, list) and v and isinstance(v[0], str):
                        result[k] = v[0]
            return result
    except (json.JSONDecodeError, OSError):
        pass
    return {}


# Composer built-in "@" commands; any other "@name" runs the script "name".
_COMPOSER_BUILTIN_REFS: frozenset[str] = frozenset({"php", "composer", "putenv"})


def _composer_script_lines(project_path: Path, name: str, seen: set[str]) -> list[str]:
    """Return every command string the composer script *name* runs.

    A script value is a string or a list of strings.  An item ``@other`` runs
    the script ``other``, whose lines are added too (recursively); ``@php``,
    ``@composer`` and ``@putenv`` are Composer built-ins and stay as text.
    *seen* holds the scripts already expanded, so a cycle cannot loop forever.
    Returns [] on any read error.
    """
    if name in seen:
        return []
    seen.add(name)
    composer = project_path / "composer.json"
    try:
        data = json.loads(composer.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    value = scripts.get(name)
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [v for v in value if isinstance(v, str)]
    else:
        return []

    lines: list[str] = []
    for item in items:
        lines.append(item)
        stripped = item.strip()
        if stripped.startswith("@"):
            parts = stripped[1:].split()
            if parts and parts[0] not in _COMPOSER_BUILTIN_REFS:
                lines.extend(_composer_script_lines(project_path, parts[0], seen))
    return lines


def _load_gemfile_scripts(project_path: Path) -> dict[str, str]:
    """Ruby Gemfile has no scripts section — return empty."""
    return {}


def _scripts_for_language(language: str, project_path: Path) -> dict[str, str]:
    """Dispatch to the correct build-file script loader for *language*."""
    if language == "javascript":
        return _load_package_scripts(project_path)
    if language == "python":
        return _load_pyproject_scripts(project_path)
    if language == "php":
        return _load_composer_scripts(project_path)
    if language == "ruby":
        return _load_gemfile_scripts(project_path)
    # Java, Kotlin, Go, C#, Rust, Swift, C++ — no script sections; use builtins.
    return {}


# ---------------------------------------------------------------------------
# Command construction from a script name
# ---------------------------------------------------------------------------


def _command_for_script(
    language: str, project_path: Path, script_name: str
) -> list[str]:
    """Return the arg list that runs *script_name* for *language*."""
    if language == "javascript":
        runner = _npm_runner_for_project(project_path)
        return runner + [script_name]
    if language == "php":
        return ["composer", script_name]
    if language == "ruby":
        return ["bundle", "exec", script_name]
    # Python and others: shlex-split the script value (used as the command).
    return []


def _command_for_script_value(script_value: str) -> list[str]:
    """Split a raw script command string into an arg list."""
    try:
        return shlex.split(script_value)
    except ValueError:
        return script_value.split()


# ---------------------------------------------------------------------------
# Built-in phase commands
# ---------------------------------------------------------------------------


def _builtin_commands_for_stage(
    stage: str,
    lang_cfg: dict,
    project: "Project",
) -> list[StageCommand]:
    """Return the built-in phase command for *stage*, or [].

    If the language declares ``build_tools`` (build file -> allowed command
    prefixes), only commands of the project's own build tool are considered:
    a pom.xml project never gets `gradle ...` and vice versa.  The first
    matching command is used; the runner substitutes mvnw/gradlew later.
    """
    builtin_phases: dict[str, list[str]] = lang_cfg.get("builtin_phases", {})
    raw_commands: list[str] = builtin_phases.get(stage, [])

    build_tools: dict[str, list[str]] = lang_cfg.get("build_tools", {})
    prefixes = build_tools.get(project.primary_build_file)
    if prefixes:
        raw_commands = [c for c in raw_commands if c.split(" ", 1)[0] in prefixes]
    if not raw_commands:
        return []

    raw = raw_commands[0]
    try:
        argv = shlex.split(raw)
    except ValueError:
        argv = raw.split()
    return [StageCommand(command=_fill_build_file(argv, project), source="builtin")]


def _fill_build_file(argv: list[str], project: "Project") -> list[str]:
    """Replace every argument that is exactly ``{build_file}`` with the primary build file.

    .NET: a folder with both a .sln and a .csproj makes plain ``dotnet format``
    fail and plain ``dotnet test`` run nothing, so every command names the file.
    """
    return [project.primary_build_file if a == "{build_file}" else a for a in argv]


# ---------------------------------------------------------------------------
# Main detection logic
# ---------------------------------------------------------------------------


def detect_commands(project: "Project", lang_cfg: dict) -> DetectionResult:
    """Detect commands for each stage of *project* using *lang_cfg*.

    Parameters
    ----------
    project:
        A discovered Project (from discovery.py).
    lang_cfg:
        The language entry from languages.toml (as returned by load_languages()).

    Returns
    -------
    DetectionResult
        .commands  — dict[stage -> list[StageCommand]]
        .skipped_scripts — list[SkippedScript]
    """
    stage_names: dict[str, list[str]] = lang_cfg.get("stage_names", {})
    stages: list[str] = lang_cfg.get("stages", [])
    language: str = project.language

    commands: dict[str, list[StageCommand]] = {stage: [] for stage in stages}
    skipped: list[SkippedScript] = []

    # --- Step 1: collect scripts from build file ---
    scripts = _scripts_for_language(language, project.path)

    # Track which underlying commands we've already scheduled, per stage,
    # to enforce the deduplication rule.
    seen_commands: dict[str, list[tuple]] = {stage: [] for stage in stages}

    fixer_patterns: list[str] = lang_cfg.get("fixer_patterns", [])

    for script_name, script_value in scripts.items():
        # Check if this script should be skipped.  For composer, every command
        # the script runs counts: all list items and any @other-script it calls.
        check_text = script_value
        if language == "php":
            check_text = "\n".join(
                _composer_script_lines(project.path, script_name, set())
            ) or script_value
        reason = _skip_reason(script_name, check_text, fixer_patterns)
        if reason is not None:
            skipped.append(SkippedScript(name=script_name, reason=reason))
            continue

        # Find which stage this script belongs to.
        stage = _stage_for_script(script_name, stage_names)
        if stage is None or stage not in commands:
            # Script doesn't map to any stage — silently ignore.
            continue

        # Build the argument list.
        argv = _command_for_script(language, project.path, script_name)
        if not argv:
            # Fallback: treat the script value as the command.
            argv = _command_for_script_value(script_value)

        # Deduplication: compare by the *underlying* command, not the npm-run wrapper.
        # For npm/yarn/pnpm: the underlying command is the script value.
        # Two scripts with the same value map to the same underlying command.
        underlying = tuple(_command_for_script_value(script_value))
        if underlying in seen_commands[stage]:
            # Duplicate — drop it.
            continue
        seen_commands[stage].append(underlying)

        commands[stage].append(
            StageCommand(command=argv, source=f"script:{script_name}")
        )

    # --- Step 2: config-file detection --------------------------------
    # languages.toml may declare ``config_commands`` rules.  A rule fires only
    # for a stage that no script already covers, and only when the project
    # itself declares the tool (config file, pyproject table or INI section).  Several
    # rules can fire for one stage (different tools); identical commands run
    # once.
    script_stages = {stage for stage in stages if commands[stage]}
    for rule in lang_cfg.get("config_commands", []):
        stage = rule.get("stage")
        if stage not in commands or stage in script_stages:
            continue
        if not _config_rule_matches(project, rule):
            continue
        argv = _fill_build_file(_command_for_script_value(rule.get("command", "")), project)
        if not argv:
            continue
        key = tuple(argv)
        if key in seen_commands[stage]:
            continue
        seen_commands[stage].append(key)
        commands[stage].append(StageCommand(command=argv, source="config"))

    # --- Step 3: built-in phase detection (for build systems that need no script) ---
    for stage in stages:
        if commands[stage]:
            continue  # already have commands; built-ins don't supplement
        builtin_cmds = _builtin_commands_for_stage(stage, lang_cfg, project)
        if builtin_cmds:
            commands[stage].extend(builtin_cmds)

    return DetectionResult(commands=commands, skipped_scripts=skipped)


# ---------------------------------------------------------------------------
# pre-llm.toml loader
# ---------------------------------------------------------------------------

_ALLOWED_TOP_LEVEL_KEYS = frozenset({"ignore", "project"})
_ALLOWED_PROJECT_KEYS = frozenset({"path", "build", "lint", "tests", "coverage"})


def load_pre_llm_toml(path: Path) -> PreLlmConfig:
    """Parse *path* as pre-llm.toml and return a PreLlmConfig.

    Returns an empty PreLlmConfig if the file does not exist.

    Raises:
        PreLlmTomlError: if the file exists but contains invalid TOML or
            unknown keys.
    """
    if not path.exists():
        return PreLlmConfig()

    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise PreLlmTomlError(f"malformed pre-llm.toml: {exc}") from exc

    # Validate top-level keys.
    unknown = set(data.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise PreLlmTomlError(
            f"pre-llm.toml: unknown key(s): {', '.join(sorted(unknown))}"
        )

    ignore: list[str] = data.get("ignore", [])
    if not isinstance(ignore, list) or not all(isinstance(x, str) for x in ignore):
        raise PreLlmTomlError("pre-llm.toml: 'ignore' must be a list of strings")

    overrides: list[ProjectOverride] = []
    raw_projects = data.get("project", [])
    if not isinstance(raw_projects, list):
        raise PreLlmTomlError("pre-llm.toml: [[project]] must be an array of tables")

    for i, proj in enumerate(raw_projects):
        if not isinstance(proj, dict):
            raise PreLlmTomlError(f"pre-llm.toml: [[project]][{i}] must be a table")
        unknown_proj = set(proj.keys()) - _ALLOWED_PROJECT_KEYS
        if unknown_proj:
            raise PreLlmTomlError(
                f"pre-llm.toml: [[project]][{i}] unknown key(s): "
                f"{', '.join(sorted(unknown_proj))}"
            )
        if "path" not in proj:
            raise PreLlmTomlError(
                f"pre-llm.toml: [[project]][{i}] missing required key 'path'"
            )
        overrides.append(
            ProjectOverride(
                path=proj["path"],
                build=proj.get("build"),
                lint=proj.get("lint"),
                tests=proj.get("tests"),
                coverage=proj.get("coverage"),
            )
        )

    return PreLlmConfig(ignore=ignore, overrides=overrides)


# ---------------------------------------------------------------------------
# Override application
# ---------------------------------------------------------------------------


def apply_overrides(
    result: DetectionResult, override: ProjectOverride
) -> DetectionResult:
    """Return a new DetectionResult with *override* applied to *result*.

    Only stages explicitly set in *override* are replaced.  Stages set to
    None in *override* are left unchanged.  The source of every replaced
    command is set to ``"override"``.
    """
    new_commands: dict[str, list[StageCommand]] = {}
    for stage, cmds in result.commands.items():
        override_value: str | None = getattr(override, stage, None)
        if override_value is not None:
            try:
                argv = shlex.split(override_value)
            except ValueError:
                argv = override_value.split()
            new_commands[stage] = [StageCommand(command=argv, source="override")]
        else:
            new_commands[stage] = list(cmds)

    return DetectionResult(
        commands=new_commands,
        skipped_scripts=list(result.skipped_scripts),
    )
