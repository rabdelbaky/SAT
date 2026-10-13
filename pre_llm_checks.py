"""Pre-LLM Checks — skeleton (Session 1) + report writer (Session 2)
+ CLI / path validation / trust notice (Session 3)
+ tool and script detection + pre-llm.toml (Session 5)
+ stage orchestration (Session 7).

Cross-platform Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tomllib
from pathlib import Path

from discovery import (
    discover_projects as _do_discover_projects,
    discovery_warnings,
    Project,
)
from detection import (
    detect_commands,
    load_pre_llm_toml,
    apply_overrides,
    PreLlmTomlError,
    DetectionResult,
)
from masking import mask_secrets
from output import collect_environment, probe_version, render_terminal
from orchestrator import (
    OrchestratorOptions,
    run_all,
    compute_exit_code,
    project_results_to_report_data,
)

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# languages.toml loader
# ---------------------------------------------------------------------------

_DEFAULT_LANGUAGES_TOML = Path(__file__).parent / "languages.toml"


class LanguagesLoadError(Exception):
    """Raised when languages.toml cannot be read or parsed."""


def load_languages(path: Path = _DEFAULT_LANGUAGES_TOML) -> dict:
    """Return the languages table from *path*.

    Keys are language names (str).  Each value is the raw TOML table for that
    language; the ``tested`` field is always present and defaults to ``false``.

    Raises:
        LanguagesLoadError: if the file is missing or contains invalid TOML.
    """
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise LanguagesLoadError(f"cannot read languages.toml: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise LanguagesLoadError(f"cannot read languages.toml: {exc}") from exc

    languages: dict = data.get("language", {})
    for entry in languages.values():
        entry.setdefault("tested", False)
    return languages


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

# Accepts: plain integer seconds ("600"), or a combination of h/m/s units
# in order ("90s", "30m", "1h", "1h30m", "1h30m45s").  No decimals.
_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def parse_duration(value: str) -> int:
    """Parse a duration string and return seconds as an int.

    Accepted formats:
      - Plain integer: ``"600"`` → 600 seconds
      - Unit suffixes (h/m/s, in order, each optional but at least one
        must be present): ``"90s"``, ``"30m"``, ``"1h"``, ``"1h30m"``,
        ``"1h30m45s"``

    Raises:
        ValueError: if *value* does not match any accepted format.
    """
    if not value:
        raise ValueError(f"empty duration string")

    # Plain integer (no letters)?
    if value.isdigit():
        v = int(value)
        if v < 0:
            raise ValueError(f"negative duration: {value!r}")
        return v

    # Must not start with a minus
    if value.startswith("-"):
        raise ValueError(f"negative duration not allowed: {value!r}")

    m = _DURATION_RE.match(value)
    if m is None or not any(m.groups()):
        raise ValueError(
            f"invalid duration {value!r}: expected plain seconds or a "
            "combination like 90s, 30m, 1h, 1h30m, 1h30m45s"
        )

    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


# ---------------------------------------------------------------------------
# output_tail cap
# ---------------------------------------------------------------------------

_MAX_LINE_LEN = 500


def cap_output_tail(
    lines: list[str],
    max_lines: int,
    max_line_len: int = _MAX_LINE_LEN,
) -> list[str]:
    """Return at most *max_lines* tail lines, each truncated to *max_line_len* chars."""
    tail = lines[-max_lines:] if len(lines) > max_lines else list(lines)
    return [line[:max_line_len] for line in tail]


# ---------------------------------------------------------------------------
# Findings cap
# ---------------------------------------------------------------------------

_MAX_FINDINGS = 50


def cap_findings(
    findings: list,
    max_count: int = _MAX_FINDINGS,
) -> tuple[list, int]:
    """Return ``(capped_list, true_total)``.

    *capped_list* has at most *max_count* items (the first *max_count*).
    *true_total* is always the original length.
    """
    total = len(findings)
    return findings[:max_count], total


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def make_relative_path(path: Path | str, root: Path) -> str:
    """Return *path* relative to *root*, always using forward slashes.

    If *path* is not under *root* (or is not absolute), return the placeholder
    ``"<external>"`` so that no absolute OS path leaks into the report.
    """
    p = Path(path)
    try:
        rel = p.relative_to(root)
        result = rel.as_posix()
        return result if result else "."
    except ValueError:
        return "<external>"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

_REPORT_SCHEMA_VERSION = "1.0"
_REPORT_SIZE_CAP = 200_000  # bytes


def _build_command_entry(
    cmd: dict,
    repo_root: Path,
    tail_lines: int,
) -> dict:
    """Convert a raw command dict into a report-ready entry."""
    # Cap and mask output_tail
    raw_tail: list[str] = cmd.get("output_tail") or []
    tail = cap_output_tail(raw_tail, max_lines=tail_lines)
    tail = [mask_secrets(line) for line in tail]

    # Cap findings
    raw_findings = cmd.get("findings")
    if raw_findings is not None:
        capped, total = cap_findings(raw_findings)
    else:
        capped, total = None, None

    # Normalise log_path to a relative forward-slash path.
    # source is a semantic label (e.g. "script:test", "override", "builtin"),
    # not a file path — pass it through unchanged.
    log_path = cmd.get("log_path")
    if log_path is not None:
        log_path = make_relative_path(log_path, repo_root)

    source = cmd.get("source")

    # Mask what the AI reads; the command that ran is never changed.
    command = cmd.get("command")
    if command is not None:
        command = [mask_secrets(arg) for arg in command]

    entry: dict = {
        "command": command,
        "scripts": cmd.get("scripts"),
        "source": source,
        "status": cmd.get("status"),
        "duration_s": cmd.get("duration_s"),
        "output_tail": tail,
        "log_path": log_path,
        "findings": capped,
    }
    if total is not None:
        entry["findings_total"] = total
    # Pass through optional metadata fields used by the orchestrator
    if cmd.get("stage") is not None:
        entry["stage"] = cmd["stage"]
    if cmd.get("reason") is not None:
        entry["reason"] = cmd["reason"]
    return entry


def build_report(
    projects_data: list[dict],
    repo_root: Path,
    tail_lines: int,
    *,
    status: str = "pass",
    environment: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Assemble and return the full report dict (not yet written to disk).

    Args:
        projects_data: list of project dicts (each with ``path``, ``language``,
            and ``commands`` keys).
        repo_root: root of the repository; used to make paths relative.
        tail_lines: maximum output_tail lines per command.
        status: overall status string for ``summary.status``.
        environment: optional ``{"os": ..., "runners": {...}}`` block (SPEC §6).
        warnings: repo-level warnings (``gitignore_missing``,
            ``no_project: <folder>``, ...) for the top-level ``warnings`` list;
            always present, empty when there are none.

    Returns:
        Ordered dict ready for JSON serialisation.
    """
    projects_out: list[dict] = []
    for proj in projects_data:
        cmds_out = [
            _build_command_entry(cmd, repo_root, tail_lines)
            for cmd in (proj.get("commands") or [])
        ]
        proj_path = proj.get("path")
        if proj_path is not None:
            proj_path = make_relative_path(proj_path, repo_root)
        proj_entry: dict = {
            "path": proj_path,
            "language": proj.get("language"),
            "build_files": list(proj.get("build_files") or []),
            "skipped_scripts": list(proj.get("skipped_scripts") or []),
            "commands": cmds_out,
        }
        if proj.get("warnings"):
            proj_entry["warnings"] = proj["warnings"]
        if proj.get("coverage") is not None:
            proj_entry["coverage"] = proj["coverage"]
        projects_out.append(proj_entry)

    report: dict = {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "summary": {
            "status": status,
            "project_count": len(projects_data),
        },
        "warnings": list(warnings or []),
        "projects": projects_out,
    }
    if environment is not None:
        report["environment"] = environment
    return report


# ---------------------------------------------------------------------------
# Report writer (with size cap)
# ---------------------------------------------------------------------------


def _serialise(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def _trim_report(report: dict, size_cap_bytes: int) -> dict:
    """Return a copy of *report* with tails trimmed until it fits in *size_cap_bytes*.

    Strategy: repeatedly halve all tails together until the serialised size is
    within the cap.  Always sets ``"truncated": true`` because this function is
    only called when the report is already over cap.  If tails are all empty
    and it still doesn't fit, set ``"truncated": true`` and return as-is.
    """
    report = copy.deepcopy(report)

    # Collect all tail lists (mutable references into the copy)
    tails: list[list[str]] = []
    for proj in report.get("projects", []):
        for cmd in proj.get("commands", []):
            if cmd.get("output_tail") is not None:
                tails.append(cmd["output_tail"])

    while len(_serialise(report).encode("utf-8")) > size_cap_bytes:
        non_empty = [t for t in tails if t]
        if not non_empty:
            break
        # Halve every non-empty tail (keeps the tail end, discards from front)
        for tail in non_empty:
            keep = max(0, len(tail) // 2)
            del tail[: len(tail) - keep]

    # This function is only reached when the report was over cap, so
    # truncated is always set regardless of whether trimming was sufficient.
    report["truncated"] = True
    return report


def write_report(
    report: dict,
    output_path: Path,
    size_cap_bytes: int = _REPORT_SIZE_CAP,
) -> None:
    """Serialise *report* to *output_path* as UTF-8 JSON, honouring *size_cap_bytes*.

    If the serialised report exceeds *size_cap_bytes*:
      1. Trim ``output_tail`` arrays (shortest first).
      2. If still too large, add ``"truncated": true``.
    """
    serialised = _serialise(report)
    if len(serialised.encode("utf-8")) > size_cap_bytes:
        report = _trim_report(report, size_cap_bytes)
        serialised = _serialise(report)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialised, encoding="utf-8")


# ---------------------------------------------------------------------------
# Trust notice
# ---------------------------------------------------------------------------


def print_trust_notice(resolved_path: Path) -> None:
    """Print the trust notice to *stderr*, naming *resolved_path*."""
    print(
        f"NOTICE: about to execute scripts defined by projects in "
        f"{resolved_path}. Only run on code you trust.",
        file=sys.stderr,
        flush=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _ExitingParser(argparse.ArgumentParser):
    """ArgumentParser that exits with code 2 and prints a single ERROR line.

    The default argparse behaviour prints to stderr and calls sys.exit(2),
    but the message format includes "error:" (lowercase) and sometimes
    multi-line usage text.  We override error() to produce the canonical
    one-line ``ERROR: …`` format and suppress usage output on errors so that
    nothing leaks to stdout.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(2)


def _timeout_type(name: str):
    """Return an argparse *type* function for a --timeout-<name> flag."""

    def _parse(value: str) -> int:
        try:
            return parse_duration(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid value for --timeout-{name}: {value!r} — {exc}"
            ) from exc

    _parse.__name__ = f"timeout_{name}"
    return _parse


def _positive_int(value: str) -> int:
    """argparse *type* for --tail-lines: an integer of at least 1."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from exc
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {n}")
    return n


def build_parser() -> _ExitingParser:
    parser = _ExitingParser(
        prog="pre-llm-checks",
        description="Gather build/lint/test evidence before an AI reviews a repo.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--path", default=".", help="Root folder to analyse.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview commands without running them.",
    )
    parser.add_argument("--output", default="pre-llm-report.json")
    parser.add_argument(
        "--steps",
        default="build,lint,tests,coverage",
        help="Comma-separated stages to run.",
    )
    parser.add_argument("--lint-anyway", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--timeout-build",
        type=_timeout_type("build"),
        default=600,
        metavar="DURATION",
    )
    parser.add_argument(
        "--timeout-lint",
        type=_timeout_type("lint"),
        default=300,
        metavar="DURATION",
    )
    parser.add_argument(
        "--timeout-tests",
        type=_timeout_type("tests"),
        default=900,
        metavar="DURATION",
    )
    parser.add_argument(
        "--timeout-coverage",
        type=_timeout_type("coverage"),
        default=900,
        metavar="DURATION",
    )
    parser.add_argument("--tail-lines", type=_positive_int, default=50)
    parser.add_argument("--config", default="pre-llm.toml")
    parser.add_argument("--add-gitignore", action="store_true")
    return parser


_VALID_STEPS = ("build", "lint", "tests", "coverage")


def _validate_path(path: Path) -> str | None:
    """Return an error message if *path* is not a readable directory, else None."""
    if not path.exists():
        return f"ERROR: path does not exist: {path}"
    if not path.is_dir():
        return f"ERROR: path is not a directory: {path}"
    if not os.access(path, os.R_OK):
        return f"ERROR: path is not readable: {path}"
    return None


# ---------------------------------------------------------------------------
# .gitignore (SPEC §2: the only file the tool may change, only with --add-gitignore)
# ---------------------------------------------------------------------------

_GITIGNORE_LINE = ".pre-llm/"


def _gitignore_covers(text: str) -> bool:
    """Return True if a .gitignore line names the .pre-llm folder."""
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith(("#", "!")):
            continue
        entry = entry.removeprefix("**/").lstrip("/")
        if entry.rstrip("/") == ".pre-llm" or entry.startswith(".pre-llm/"):
            return True
    return False


def _read_gitignore(path: Path) -> str | None:
    """Return the .gitignore text, "" if missing, None if it cannot be read."""
    if not path.exists():
        return ""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _add_gitignore(path: Path) -> None:
    """Create *path* with ``.pre-llm/``, or append that line if not covered.

    Touches nothing else: existing content is kept byte for byte; a newline is
    added first only when the file does not end with one.
    """
    if not path.exists():
        path.write_bytes((_GITIGNORE_LINE + "\n").encode("utf-8"))
        return
    data = path.read_bytes()
    if _gitignore_covers(data.decode("utf-8")):
        return
    prefix = b"" if not data or data.endswith(b"\n") else b"\n"
    with open(path, "ab") as fh:
        fh.write(prefix + (_GITIGNORE_LINE + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _write_empty_report(
    output_path: Path,
    root: Path,
    status: str,
    warnings: list[str] | None = None,
) -> None:
    """Write a report with ``projects: []`` (early exits: error or no_project)."""
    try:
        report = build_report(
            projects_data=[],
            repo_root=root,
            tail_lines=1,
            status=status,
            environment=collect_environment([]),
            warnings=warnings,
        )
        write_report(report, output_path)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not write report: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Known before any check, so every return below writes a report (SPEC §6).
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    # Parse requested steps; reject unknown names before doing anything else.
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    for step in steps:
        if step not in _VALID_STEPS:
            print(f"ERROR: unknown step: {step}", file=sys.stderr)
            _write_empty_report(output_path, Path.cwd(), "error")
            return 2

    root = Path(args.path).resolve()

    # Trust notice is always first — goes to stderr, names the resolved folder.
    print_trust_notice(root)

    # Validate the path *after* printing the notice (notice is unconditional).
    err = _validate_path(root)
    if err is not None:
        print(err, file=sys.stderr)
        _write_empty_report(output_path, root, "error")
        return 2

    # Allow tests (and advanced users) to override the languages.toml path.
    languages_toml = Path(
        os.environ.get("PRE_LLM_LANGUAGES_TOML", _DEFAULT_LANGUAGES_TOML)
    )
    try:
        languages = load_languages(languages_toml)
    except LanguagesLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _write_empty_report(output_path, root, "error")
        return 2

    # Load pre-llm.toml (optional; lives at repo root).
    config_path = root / args.config
    try:
        pre_llm_cfg = load_pre_llm_toml(config_path)
    except PreLlmTomlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _write_empty_report(output_path, root, "error")
        return 2

    # Discover projects, honouring the ignore list from pre-llm.toml.
    projects = _discover_projects(root, languages, ignore=pre_llm_cfg.ignore)

    # no_project / unsupported_extension: (warning, folder) pairs.
    found_warnings = discovery_warnings(
        root, languages, projects, ignore=pre_llm_cfg.ignore
    )

    if not projects:
        print("No supported projects found.", file=sys.stderr)
        _write_empty_report(
            output_path,
            root,
            "no_project",
            warnings=[f"{w}: {folder}" for w, folder in found_warnings],
        )
        return 3

    # Build a mapping from normalised project path → override (if any).
    override_map: dict[Path, object] = {}
    for ov in pre_llm_cfg.overrides:
        ov_path = (root / ov.path).resolve()
        matched = [p for p in projects if p.path.resolve() == ov_path]
        if not matched:
            print(
                f"WARNING: pre-llm.toml override path {ov.path!r} "
                "matches no discovered project",
                file=sys.stderr,
            )
        else:
            override_map[ov_path] = ov

    if args.dry_run:
        _print_dry_run(projects, languages, override_map, root=root)
        return 0

    orch_opts = OrchestratorOptions(
        steps=steps,
        lint_anyway=args.lint_anyway,
        dry_run=args.dry_run,
        tail_lines=args.tail_lines,
        timeout_build=float(args.timeout_build),
        timeout_lint=float(args.timeout_lint),
        timeout_tests=float(args.timeout_tests),
        timeout_coverage=float(args.timeout_coverage),
        verbose=args.verbose,
    )

    # Logs live in <repo root>/.pre-llm/logs/ (SPEC §6); the .gitignore that
    # must cover them is the repo root's.
    pre_llm_dir = root / ".pre-llm"
    gitignore_path = root / ".gitignore"
    gitignore_missing = False
    if args.add_gitignore:
        try:
            _add_gitignore(gitignore_path)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"WARNING: could not update .gitignore: {exc}", file=sys.stderr)
            gitignore_missing = True
    elif not gitignore_path.exists():
        print(
            "WARNING: .gitignore missing — logs will not be gitignored.",
            file=sys.stderr,
        )
        gitignore_missing = True
    else:
        content = _read_gitignore(gitignore_path)
        if content is not None and not _gitignore_covers(content):
            print(
                "WARNING: .pre-llm not in .gitignore — logs will not be gitignored.",
                file=sys.stderr,
            )
            gitignore_missing = True

    # Repo-level warnings: (where, warning) for the terminal, strings for the report.
    terminal_warnings: list[tuple[str, str]] = []
    report_warnings: list[str] = []
    if gitignore_missing:
        terminal_warnings.append(("(repo)", "gitignore_missing"))
        report_warnings.append("gitignore_missing")
    for w, folder in found_warnings:
        terminal_warnings.append((folder, w))
        report_warnings.append(f"{w}: {folder}")

    was_interrupted = False
    results = []
    summary_status = "pass"

    try:
        results, was_interrupted = run_all(
            projects=projects,
            languages=languages,
            detection_fn=detect_commands,
            override_map=override_map,
            opts=orch_opts,
            repo_root=root,
            log_dir=pre_llm_dir / "logs",
        )
        exit_code = compute_exit_code(results, was_interrupted=was_interrupted)
        if exit_code == 130:
            summary_status = "interrupted"
        elif exit_code == 1:
            summary_status = "fail"
        else:
            summary_status = "pass"
    except KeyboardInterrupt:
        was_interrupted = True
        summary_status = "interrupted"
        exit_code = 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: internal error: {exc}", file=sys.stderr)
        summary_status = "error"
        exit_code = 2

    # Human-readable table (stdout).  Never allowed to change the exit code.
    try:
        if results:
            print(
                render_terminal(
                    results,
                    root,
                    verbose=args.verbose,
                    repo_warnings=terminal_warnings,
                ),
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not print results table: {exc}", file=sys.stderr)

    # Build and write report (even on crash or interrupt)
    try:
        environment = collect_environment(
            results,
            version_fn=(lambda exe, cwd: None) if was_interrupted else probe_version,
        )
        projects_data = project_results_to_report_data(results, root)
        report = build_report(
            projects_data=projects_data,
            repo_root=root,
            tail_lines=args.tail_lines,
            status=summary_status,
            environment=environment,
            warnings=report_warnings,
        )
        write_report(report, output_path)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not write report: {exc}", file=sys.stderr)

    return exit_code


# ---------------------------------------------------------------------------
# Project discovery (Session 4)
# ---------------------------------------------------------------------------


def _discover_projects(
    root: Path,
    languages: dict,
    ignore: list[str] | None = None,
) -> list[Project]:
    """Walk *root* and return discovered projects (delegates to discovery module)."""
    return _do_discover_projects(root, languages, ignore=ignore)


def _print_dry_run(
    projects: list[Project],
    languages: dict,
    override_map: dict | None = None,
    *,
    root: Path,
) -> None:
    """Print per-project, per-stage: each command that would run with its source,
    then any skipped scripts with reasons.  Commands are shown with secrets
    masked; project paths are relative to *root* with forward slashes (``.``
    for the root), like the table.

    Format (SPEC §11 --dry-run):
      <project_path>  <language>  <build_files>  [untested]
        <stage>: <command>  [<source>]
        ...
        skipped: <name>  (<reason>)
        ...
    """
    if override_map is None:
        override_map = {}

    for p in projects:
        build_files_str = ", ".join(p.build_files)
        untested = "  [untested]" if not p.tested else ""
        print(
            f"{make_relative_path(p.path, root)}  {p.language}  "
            f"{build_files_str}{untested}"
        )

        lang_cfg = languages.get(p.language, {})
        result: DetectionResult = detect_commands(p, lang_cfg)

        # Apply any override for this project.
        ov = override_map.get(p.path.resolve())
        if ov is not None:
            result = apply_overrides(result, ov)

        # Print commands per stage.
        for stage in lang_cfg.get("stages", []):
            cmds = result.commands.get(stage, [])
            for cmd in cmds:
                argv_str = mask_secrets(" ".join(cmd.command))
                print(f"  {stage}: {argv_str}  [{cmd.source}]")

        # Print skipped scripts.
        for skip in result.skipped_scripts:
            print(f"  skipped: {skip.name}  ({skip.reason})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
