"""Stage orchestrator for Pre-LLM Checks (Session 7).

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

Rules (SPEC §3 steps 5–7, §5, §6, §8):
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
    dep_error_phrases: phrases in a failed command's output that turn
        status="fail" into status="dependencies_missing" (warning, not fail).
- Per-stage timeouts from opts (build 10m, lint 5m, tests 15m, coverage 15m).
- Each command result: status, duration_s, output_tail, log_path, findings=null.
- On KeyboardInterrupt: mark current command interrupted, set result.interrupted=True,
  and return the partial result so the caller can write the report and exit 130.
- Log files go in <log_dir>/<project_path_slug>/<stage>-<n>.log.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from detection import DetectionResult, StageCommand
from discovery import Project
from runner import run_command, CommandResult


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
    log_path: Optional[str]  # relative forward-slash path, or None
    findings: None = None  # v1: always null


@dataclass
class StageResult:
    """Outcome of one stage for one project."""

    stage: str
    status: str  # pass | fail | timeout | skipped | no_linter_configured |
    # dependencies_missing | tool_not_installed | interrupted
    reason: Optional[str] = None  # e.g. "build_gate", "dependencies_missing"
    commands: list[CommandRecord] = field(default_factory=list)


@dataclass
class ProjectResult:
    """All results for one project."""

    project: Project
    stages: list[StageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    interrupted: bool = False

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


def _matches_dep_error(output: str, phrases: list[str]) -> bool:
    """Return True if *output* contains any phrase from *phrases*."""
    for phrase in phrases:
        if phrase in output:
            return True
    return False


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
        command=cmd.command,
        source=cmd.source,
        stage=stage,
        status=result.status,
        duration_s=result.duration_s,
        output_tail=result.output_tail,
        log_path=_relative_path(log_path, repo_root),
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
    result = ProjectResult(project=project)
    stages_order: list[str] = lang_cfg.get(
        "stages", ["build", "lint", "tests", "coverage"]
    )
    dep_folders: list[str] = lang_cfg.get("dep_folders", [])
    dep_error_phrases: list[str] = lang_cfg.get("dep_error_phrases", [])

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
    #       (overrides bypass the folder check by design).
    # A missing folder means deps are not installed; all stages are skipped.
    if (
        dep_folders
        and active_stages
        and not _all_commands_from_overrides(detection, active_stages)
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
            if record.status == "fail" and dep_error_phrases:
                full_output = "\n".join(record.output_tail)
                if _matches_dep_error(full_output, dep_error_phrases):
                    record.status = "dependencies_missing"
                    result.warnings.append("dependencies_missing")

            stage_result.commands.append(record)

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
        path, language, commands (flat list across all stages)
    """
    projects_data: list[dict] = []
    for pr in results:
        cmds_out: list[dict] = []
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
        projects_data.append(
            {
                "path": pr.project.path,
                "language": pr.project.language,
                "commands": cmds_out,
                "warnings": pr.warnings,
            }
        )
    return projects_data
