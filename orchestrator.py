"""Stage orchestrator for Pre-LLM Checks (Sessions 7–8).

Public API
----------
OrchestratorOptions
    Configuration knobs (steps, timeouts, dry_run, lint_anyway, tail_lines, etc.)

StageResult
    Outcome of one stage for one project.

ProjectResult
    All stage results for one project plus project-level metadata.

run_project(project, lang_cfg, detection_result, opts, log_dir) -> ProjectResult
    Run all stages for one project in order: build → lint → tests → coverage.
    Enforces the build gate, dependency checks, no_linter_configured, and
    nothing_to_run rules.  Each project is independent; never raises.

run_all(projects, languages, detection_fn, opts, repo_root) -> list[ProjectResult]
    Run every project in sequence (projects are independent; one failure never
    stops the others).  Returns results in the same order as *projects*.

Rules (SPEC §3 steps 5–7, §5, §6, §8–9):
- Stage order: build, lint, tests, coverage (from lang_cfg "stages" list).
- Build gate: if build fails or times out, all subsequent stages for that
  project are skipped (status="skipped", reason="build_gate") UNLESS
  --lint-anyway is set (lint still runs) OR --steps excludes build (gate off).
- --steps: only run the listed stages; if build is excluded, gate is off.
- A project whose lint stage has no commands gets status no_linter_configured.
- A project with no commands at all for any stage gets nothing_to_run warning.
- Dependency check (data-driven from languages.toml):
    dep_folders: optional folder check; if any folder is absent, all stages
        are skipped with status="skipped", reason="dependencies_missing".
    dep_declared_keys: the folder check is skipped when the JSON build file
        declares no packages in any of these keys (nothing to install).
    dep_error_phrases: phrases in a failed command's output that turn
        status="fail" into status="dependencies_missing" (warning, not fail).
    dep_error_patterns: optional regexes (re.MULTILINE), same effect as phrases.
- No tests found (data-driven): a tests stage that passed is marked
  status="skipped", reason="no_tests_found" (its commands too) when the full
  log matches one of lang_cfg["no_tests_patterns"] and none of
  lang_cfg["tests_ran_patterns"] (regexes, re.MULTILINE).  E.g. Maven
  "No tests to run." with no "Tests run: N" line.  The table shows SKIP.
  A language with coverage_needs_tests = true gets the same check on its
  coverage stage; the coverage stage then FAILS with reason no_tests_found
  (no coverage is read); e.g. Ruby, where SimpleCov says 100%.
  no_tests_fail_patterns: a tests (or, with coverage_needs_tests, coverage)
  stage that FAILED only because the runner found no tests (log matches one of
  these and none of tests_ran_patterns) gets reason no_tests_found too: tests
  skipped, coverage fail.  E.g. Swift's "error: no tests found" for a package
  with no test target.
- Tests failed -> coverage skipped: if the tests stage ran in this run and
  failed or timed out, the coverage stage does not run (status="skipped",
  reason="tests_failed").
- No tests found -> coverage fails: if the tests stage ran in this run and
  found no tests (reason no_tests_found), the coverage stage does not run
  (status="fail", reason="no_tests_found").  A tests stage with no command
  (nothing_to_run) or --steps without tests leaves coverage alone.
- Per-stage timeouts from opts (build 10m, lint 5m, tests 15m, coverage 15m).
- Each command result: status, duration_s, output_tail, log_path, findings=null.
- On KeyboardInterrupt: mark current command interrupted, set result.interrupted=True,
  and return the partial result so the caller can write the report and exit 130.
- Log files go in <log_dir>/<project_path_slug>/<stage>-<n>.log.
- Coverage (Session 8): after the coverage stage commands complete, attempt to
  read coverage files declared in lang_cfg["coverage_files"].  Only files
  written during this run (mtime > stage_start_time - 2s) are used.  Results
  are attached to StageResult.coverage_data.  Warnings (coverage_stale,
  coverage_unreadable, coverage_missing) are propagated to ProjectResult.warnings.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from coverage_readers import CoverageData, read_project_coverage
from detection import DetectionResult, SkippedScript, StageCommand
from discovery import Project
from runner import displayed_command, run_command, CommandResult


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorOptions:
    """Configuration for a run."""

    steps: list[str] = field(
        default_factory=lambda: ["build", "lint", "tests", "coverage"]
    )
    lint_anyway: bool = False
    dry_run: bool = False
    tail_lines: int = 50
    timeout_build: float = 600.0  # 10 min
    timeout_lint: float = 300.0  # 5 min
    timeout_tests: float = 900.0  # 15 min
    timeout_coverage: float = 900.0  # 15 min
    secrets: list[str] = field(default_factory=list)
    verbose: bool = False

    def timeout_for(self, stage: str) -> float:
        return {
            "build": self.timeout_build,
            "lint": self.timeout_lint,
            "tests": self.timeout_tests,
            "coverage": self.timeout_coverage,
        }.get(stage, 300.0)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CommandRecord:
    """Serialisable record of a single command execution."""

    command: list[str]
    source: str
    stage: str
    status: str  # pass | fail | timeout | interrupted | tool_not_installed |
    # skipped | no_linter_configured | dependencies_missing
    duration_s: float
    output_tail: list[str]
    log_path: Optional[str]  # absolute path (build_report relativises it), or None
    findings: None = None  # v1: always null


@dataclass
class StageResult:
    """Outcome of one stage for one project."""

    stage: str
    status: str  # pass | fail | timeout | skipped | no_linter_configured |
    # dependencies_missing | tool_not_installed | interrupted
    reason: Optional[str] = None  # e.g. "build_gate", "dependencies_missing"
    commands: list[CommandRecord] = field(default_factory=list)
    coverage_data: Optional[CoverageData] = None  # set for "coverage" stage only


@dataclass
class ProjectResult:
    """All results for one project."""

    project: Project
    stages: list[StageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    interrupted: bool = False
    skipped_scripts: list[SkippedScript] = field(default_factory=list)

    def stage_status(self, stage: str) -> Optional[str]:
        for s in self.stages:
            if s.stage == stage:
                return s.status
        return None

    def overall_status(self) -> str:
        """Worst-wins: fail > timeout > dependencies_missing > tool_not_installed > pass."""
        if self.interrupted:
            return "interrupted"
        statuses = [s.status for s in self.stages]
        if "fail" in statuses:
            return "fail"
        if "timeout" in statuses:
            return "timeout"
        if "tool_not_installed" in statuses:
            return "tool_not_installed"
        if all(
            s
            in (
                "pass",
                "skipped",
                "no_linter_configured",
                "dependencies_missing",
                "nothing_to_run",
            )
            for s in statuses
        ):
            return "pass"
        return "pass"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(path: Path, repo_root: Path) -> str:
    """Return a filesystem-safe slug for a project path."""
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
        parts = rel.parts
    except ValueError:
        parts = path.resolve().parts[-2:]
    if not parts:
        return "_root_"
    return "_".join(p.replace(" ", "_") for p in parts) or "_root_"


def _log_path(log_dir: Path, slug: str, stage: str, n: int) -> Path:
    return log_dir / slug / f"{stage}-{n}.log"


def _matches_dep_error(
    output: str, phrases: list[str], patterns: list[str] | None = None
) -> bool:
    """Return True if *output* contains any phrase or matches any regex pattern.

    Patterns use re.MULTILINE; an invalid pattern is skipped.
    """
    for phrase in phrases:
        if phrase in output:
            return True
    for pattern in patterns or []:
        try:
            if re.search(pattern, output, re.MULTILINE):
                return True
        except re.error:
            continue
    return False


def _ran_no_tests(
    records: list[CommandRecord], no_tests: list[str], ran: list[str]
) -> bool:
    """Return True if the passed tests commands ran no test at all.

    Reads each command's full log (masked; falls back to output_tail), so a
    "Tests run: N" line far above the tail still counts.  A pattern that
    raises re.error is skipped.
    """
    if not no_tests or not records:
        return False
    texts = []
    for rec in records:
        text = None
        if rec.log_path:
            try:
                text = Path(rec.log_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = None
        texts.append(text if text is not None else "\n".join(rec.output_tail))
    full = "\n".join(texts)

    def _any(patterns: list[str]) -> bool:
        for pattern in patterns:
            try:
                if re.search(pattern, full, re.MULTILINE):
                    return True
            except re.error:
                continue
        return False

    return _any(no_tests) and not _any(ran)


def _declares_no_dependencies(project: Project, keys: list[str]) -> bool:
    """Return True if the JSON build file declares no packages in any of *keys*.

    False when *keys* is empty or the build file cannot be read as a JSON object.
    """
    if not keys:
        return False
    try:
        with open(project.path / project.primary_build_file, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return not any(isinstance(data.get(k), dict) and data.get(k) for k in keys)


def _all_commands_from_overrides(detection: DetectionResult, stages: list[str]) -> bool:
    """Return True if every command in every active stage comes from an override.

    When a project's commands are entirely from pre-llm.toml overrides, the
    dependency folder check is bypassed: the override author is explicitly
    telling the tool what to run, independent of the normal dep setup.
    Returns False if there are no commands at all (handled separately).
    """
    has_any = False
    for stage in stages:
        for cmd in detection.commands.get(stage, []):
            has_any = True
            if cmd.source != "override":
                return False
    return has_any


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Single-command runner wrapper
# ---------------------------------------------------------------------------


def _run_one(
    cmd: StageCommand,
    stage: str,
    cwd: Path,
    log_path: Path,
    opts: OrchestratorOptions,
    repo_root: Path,
) -> CommandRecord:
    """Run one StageCommand and return a CommandRecord."""
    if opts.dry_run:
        # Should never be reached (caller guards), but be safe
        return CommandRecord(
            command=cmd.command,
            source=cmd.source,
            stage=stage,
            status="skipped",
            duration_s=0.0,
            output_tail=[],
            log_path=None,
        )

    result: CommandResult = run_command(
        args=cmd.command,
        cwd=cwd,
        timeout_s=opts.timeout_for(stage),
        log_path=log_path,
        tail_lines=opts.tail_lines,
        secrets=opts.secrets,
    )

    return CommandRecord(
        # mvn/gradle show as the wrapper that really ran (mvnw, gradlew.bat).
        command=displayed_command(cmd.command, cwd),
        source=cmd.source,
        stage=stage,
        status=result.status,
        duration_s=result.duration_s,
        output_tail=result.output_tail,
        # Absolute path; build_report makes it repo-relative with forward slashes.
        log_path=str(log_path.absolute()),
        findings=None,
    )


# ---------------------------------------------------------------------------
# Core: run one project
# ---------------------------------------------------------------------------


def run_project(
    project: Project,
    lang_cfg: dict,
    detection: DetectionResult,
    opts: OrchestratorOptions,
    log_dir: Path,
    repo_root: Path,
) -> ProjectResult:
    """Run all stages for *project* and return a :class:`ProjectResult`.

    Skips stages before running only when:
      - nothing_to_run:         no commands detected for ANY active stage
      - dependencies_missing:   language has dep_folders, at least one must
                                exist, none do, AND not all commands are
                                overrides (overrides bypass the folder check)
      - build_gate:             build failed/timed-out; subsequent stages skip
                                (lint exempt if --lint-anyway)
      - no_linter_configured:   lint stage specifically has no commands
      - per-stage nothing:      a non-lint stage has no commands after
                                the above checks pass

    Sets result.interrupted=True and returns the partial result on Ctrl+C.
    Never raises.
    """
    result = ProjectResult(
        project=project, skipped_scripts=list(detection.skipped_scripts)
    )
    stages_order: list[str] = lang_cfg.get(
        "stages", ["build", "lint", "tests", "coverage"]
    )
    dep_folders: list[str] = lang_cfg.get("dep_folders", [])
    dep_error_phrases: list[str] = lang_cfg.get("dep_error_phrases", [])
    dep_error_patterns: list[str] = lang_cfg.get("dep_error_patterns", [])
    no_tests_patterns: list[str] = lang_cfg.get("no_tests_patterns", [])
    tests_ran_patterns: list[str] = lang_cfg.get("tests_ran_patterns", [])
    no_tests_fail_patterns: list[str] = lang_cfg.get("no_tests_fail_patterns", [])
    dep_declared_keys: list[str] = lang_cfg.get("dep_declared_keys", [])

    # Filter to only the requested steps
    active_stages = [s for s in stages_order if s in opts.steps]

    slug = _slug(project.path, repo_root)

    # --- Check if any stage has commands at all -------------------------
    has_any_command = any(bool(detection.commands.get(s)) for s in active_stages)
    if not has_any_command:
        result.warnings.append("nothing_to_run")
        for stage in active_stages:
            result.stages.append(
                StageResult(stage=stage, status="skipped", reason="nothing_to_run")
            )
        return result

    # --- Dependency folder check ----------------------------------------
    # Only runs when:
    #   (a) the language declares dep_folders (non-empty list), AND
    #   (b) not ALL active commands come from pre-llm.toml overrides
    #       (overrides bypass the folder check by design), AND
    #   (c) the build file declares at least one package (dep_declared_keys).
    # A missing folder means deps are not installed; all stages are skipped.
    if (
        dep_folders
        and active_stages
        and not _all_commands_from_overrides(detection, active_stages)
        and not _declares_no_dependencies(project, dep_declared_keys)
    ):
        found_dep_folder = any((project.path / f).is_dir() for f in dep_folders)
        if not found_dep_folder:
            # Report the first declared folder as the "expected" one.
            reason_str = f"dependencies_missing: expected {dep_folders[0]}"
            result.warnings.append("dependencies_missing")
            for stage in active_stages:
                result.stages.append(
                    StageResult(
                        stage=stage,
                        status="skipped",
                        reason=reason_str,
                    )
                )
            return result

    # --- Gate flag: build gate is on only if build is in active_stages --
    gate_active = "build" in active_stages

    build_failed = False  # set True when build fails/times out

    for stage in active_stages:
        cmds: list[StageCommand] = detection.commands.get(stage, [])

        # --- Build gate enforcement ------------------------------------
        if build_failed and stage != "lint":
            result.stages.append(
                StageResult(stage=stage, status="skipped", reason="build_gate")
            )
            continue
        if build_failed and stage == "lint" and not opts.lint_anyway:
            result.stages.append(
                StageResult(stage=stage, status="skipped", reason="build_gate")
            )
            continue

        # --- Coverage after the tests stage --------------------------
        tests_st = next((s for s in result.stages if s.stage == "tests"), None)
        if stage == "coverage" and tests_st is not None:
            if tests_st.status in ("fail", "timeout"):
                result.stages.append(
                    StageResult(stage=stage, status="skipped", reason="tests_failed")
                )
                continue
            if tests_st.reason == "no_tests_found":
                result.stages.append(
                    StageResult(stage=stage, status="fail", reason="no_tests_found")
                )
                continue

        # --- no_linter_configured ------------------------------------
        if stage == "lint" and not cmds:
            result.stages.append(
                StageResult(stage=stage, status="no_linter_configured")
            )
            continue

        # --- Nothing to run for non-lint stages ----------------------
        if not cmds:
            result.stages.append(
                StageResult(stage=stage, status="skipped", reason="nothing_to_run")
            )
            continue

        # --- Run all commands for this stage -------------------------
        stage_result = StageResult(stage=stage, status="pass")

        # Record the start time for the coverage freshness check.
        # We record it before the first command so any file written by
        # the command is definitely newer than this timestamp.
        stage_start_time: float = time.time()

        for n, cmd in enumerate(cmds):
            lp = _log_path(log_dir, slug, stage, n)
            try:
                record = _run_one(cmd, stage, project.path, lp, opts, repo_root)
            except KeyboardInterrupt:
                # Mark current stage interrupted, mark project interrupted,
                # then return the partial result instead of re-raising.
                # run_all checks result.interrupted and sets was_interrupted.
                interrupted_record = CommandRecord(
                    command=cmd.command,
                    source=cmd.source,
                    stage=stage,
                    status="interrupted",
                    duration_s=0.0,
                    output_tail=[],
                    log_path=None,
                )
                stage_result.commands.append(interrupted_record)
                stage_result.status = "interrupted"
                result.stages.append(stage_result)
                result.interrupted = True
                return result  # caller checks .interrupted

            # --- dep_error_phrases post-processing --------------------
            if record.status == "fail" and (dep_error_phrases or dep_error_patterns):
                full_output = "\n".join(record.output_tail)
                if _matches_dep_error(full_output, dep_error_phrases, dep_error_patterns):
                    record.status = "dependencies_missing"
                    if "dependencies_missing" not in result.warnings:
                        result.warnings.append("dependencies_missing")

            stage_result.commands.append(record)

            # --- tool_not_installed: warning, never a pass -------------
            if record.status == "tool_not_installed":
                if stage_result.status not in ("fail", "timeout"):
                    stage_result.status = "tool_not_installed"
                if "tool_not_installed" not in result.warnings:
                    result.warnings.append("tool_not_installed")

            # Worst-wins for the stage
            if record.status in (
                "fail",
                "timeout",
                "interrupted",
                "dependencies_missing",
            ):
                if record.status in ("fail", "timeout"):
                    stage_result.status = record.status
                elif record.status == "dependencies_missing":
                    stage_result.status = "dependencies_missing"
                elif record.status == "interrupted":
                    stage_result.status = "interrupted"

        # --- Tests that ran no test: SKIP, not a vacuous PASS --------
        if (
            (stage == "tests" or (stage == "coverage" and lang_cfg.get("coverage_needs_tests")))
            and (
                (stage_result.status == "pass"
                 and _ran_no_tests(stage_result.commands, no_tests_patterns, tests_ran_patterns))
                or (stage_result.status == "fail"
                    and _ran_no_tests(stage_result.commands, no_tests_fail_patterns, tests_ran_patterns))
            )
        ):
            for rec in stage_result.commands:
                rec.status = "skipped"
            stage_result.status = "fail" if stage == "coverage" else "skipped"
            stage_result.reason = "no_tests_found"

        # --- Coverage file reading (Session 8) -----------------------
        if (
            stage == "coverage"
            and stage_result.status not in ("dependencies_missing", "tool_not_installed")
            and stage_result.reason != "no_tests_found"
        ):
            coverage_files: list[str] = lang_cfg.get("coverage_files", [])
            output_texts = ["\n".join(rec.output_tail) for rec in stage_result.commands]
            cov_data = read_project_coverage(
                project_path=project.path,
                coverage_files=coverage_files,
                stage_start_time=stage_start_time,
                output_texts=output_texts,
            )
            stage_result.coverage_data = cov_data
            # Propagate coverage warnings to project-level warnings
            for warn in cov_data.warnings:
                if warn not in result.warnings:
                    result.warnings.append(warn)

        result.stages.append(stage_result)

        # --- Build gate trigger ------------------------------------
        if gate_active and stage == "build":
            if stage_result.status in ("fail", "timeout"):
                build_failed = True

    return result


# ---------------------------------------------------------------------------
# Run all projects
# ---------------------------------------------------------------------------

# Type alias for the detection function injected by the caller
DetectionFn = Callable[[Project, dict], DetectionResult]


def run_all(
    projects: list[Project],
    languages: dict,
    detection_fn: DetectionFn,
    override_map: dict,  # project.path.resolve() -> ProjectOverride
    opts: OrchestratorOptions,
    repo_root: Path,
    log_dir: Optional[Path] = None,
) -> tuple[list[ProjectResult], bool]:
    """Run every project in *projects* independently and return results.

    Parameters
    ----------
    projects:
        Discovered projects (from discovery.discover_projects).
    languages:
        The languages dict (from load_languages()).
    detection_fn:
        Callable(project, lang_cfg) -> DetectionResult.  Injected so callers
        can pass apply_overrides-wrapped detection or a stub for tests.
    override_map:
        Mapping from resolved project path to ProjectOverride (may be empty).
    opts:
        OrchestratorOptions for this run.
    repo_root:
        Absolute root of the repo; used for relative log paths.
    log_dir:
        Where to write log files.  Defaults to <repo_root>/.pre-llm/logs/.

    Returns
    -------
    (results, was_interrupted)
        *results*: one ProjectResult per project (same order as *projects*).
        *was_interrupted*: True if any project was interrupted by Ctrl+C.
    """
    if log_dir is None:
        log_dir = repo_root / ".pre-llm" / "logs"

    if opts.dry_run:
        # Dry-run: return empty results (caller already printed the preview)
        return [], False

    results: list[ProjectResult] = []
    was_interrupted = False

    for project in projects:
        lang_cfg = languages.get(project.language, {})

        # Detect commands
        detection = detection_fn(project, lang_cfg)

        # Apply overrides
        ov = override_map.get(project.path.resolve())
        if ov is not None:
            from detection import apply_overrides as _apply_ov

            detection = _apply_ov(detection, ov)

        proj_result = run_project(
            project=project,
            lang_cfg=lang_cfg,
            detection=detection,
            opts=opts,
            log_dir=log_dir,
            repo_root=repo_root,
        )
        results.append(proj_result)

        if proj_result.interrupted:
            was_interrupted = True
            break  # stop processing further projects; report will be written

    return results, was_interrupted


# ---------------------------------------------------------------------------
# Exit code computation
# ---------------------------------------------------------------------------


def compute_exit_code(
    results: list[ProjectResult],
    was_interrupted: bool,
    no_projects: bool = False,
) -> int:
    """Return the exit code for a completed run.

    SPEC §8:
      0 — all passed or only warnings
      1 — something failed or timed out
      2 — script error (not computed here; caller raises SystemExit(2))
      3 — no supported project
      130 — interrupted (Ctrl+C)
    """
    if was_interrupted:
        return 130
    if no_projects:
        return 3
    for proj_result in results:
        for stage in proj_result.stages:
            if stage.status in ("fail", "timeout"):
                return 1
            for cmd in stage.commands:
                if cmd.status in ("fail", "timeout"):
                    return 1
    return 0


# ---------------------------------------------------------------------------
# Report data conversion
# ---------------------------------------------------------------------------


def project_results_to_report_data(
    results: list[ProjectResult],
    repo_root: Path,
) -> list[dict]:
    """Convert orchestrator results into the format expected by build_report().

    Each project dict has:
        path, language, build_files (repo-relative, forward slashes),
        skipped_scripts ([{"name", "reason"}]), commands (flat list across
        all stages), warnings, coverage (optional)
    """
    projects_data: list[dict] = []
    for pr in results:
        cmds_out: list[dict] = []
        coverage_out: Optional[dict] = None

        for stage_result in pr.stages:
            if stage_result.commands:
                for rec in stage_result.commands:
                    cmds_out.append(
                        {
                            "command": rec.command,
                            "scripts": None,
                            "source": rec.source,
                            "status": rec.status,
                            "duration_s": rec.duration_s,
                            "output_tail": rec.output_tail,
                            "log_path": rec.log_path,
                            "findings": rec.findings,
                            "stage": rec.stage,
                            "reason": stage_result.reason,
                        }
                    )
            else:
                # No commands ran — emit a synthetic no-op entry for the stage
                cmds_out.append(
                    {
                        "command": None,
                        "scripts": None,
                        "source": None,
                        "status": stage_result.status,
                        "duration_s": 0.0,
                        "output_tail": [],
                        "log_path": None,
                        "findings": None,
                        "stage": stage_result.stage,
                        "reason": stage_result.reason,
                    }
                )

            # Attach coverage data to the report (coverage stage only)
            if (
                stage_result.stage == "coverage"
                and stage_result.coverage_data is not None
            ):
                cov = stage_result.coverage_data
                coverage_out = {
                    "results": [
                        {
                            "line_pct": r.line_pct,
                            "branch_pct": r.branch_pct,
                            "source_file": _relative_path(
                                Path(r.source_file), repo_root
                            )
                            if r.source_file != "<output>"
                            else "<output>",
                            "format": r.format,
                        }
                        for r in cov.results
                    ],
                    "lowest_line_pct": cov.lowest_line_pct(),
                    "warnings": cov.warnings,
                }

        proj_entry: dict = {
            "path": pr.project.path,
            "language": pr.project.language,
            "build_files": [
                _relative_path(pr.project.path / bf, repo_root)
                for bf in pr.project.build_files
            ],
            "skipped_scripts": [
                {"name": s.name, "reason": s.reason} for s in pr.skipped_scripts
            ],
            "commands": cmds_out,
            "warnings": pr.warnings,
        }
        if coverage_out is not None:
            proj_entry["coverage"] = coverage_out

        projects_data.append(proj_entry)
    return projects_data
