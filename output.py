"""Terminal output and environment block for Pre-LLM Checks (Session 9).

Public API
----------
render_terminal(results, repo_root, *, verbose=False) -> str
    The human-readable result: a table (one row per project), then optional
    Commands (verbose), Details, Warnings sections, then a one-line Summary.
    See tests/fixtures/EXPECTED.md ("terminal-table") for the exact format.

cell_text(stage_result) -> str
    One table cell.  Worst wins: INTR > FAIL > TIMEOUT > WARN > PASS > SKIP.
    A passing coverage stage shows the lowest line percentage (e.g. "72.0%").

project_state(project_result) -> "passed" | "warnings" | "failed"

collect_environment(results, version_fn=probe_version, os_name=None) -> dict
    {"os": "...", "runners": {name: first line of --version | "unknown"}}
    for every executable that actually ran (SPEC §6).

probe_version(exe, cwd) -> str | None
    Run ``<exe> --version`` (shell=False, 10 s) and return the first output
    line, or None on any failure.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Callable, Optional

from orchestrator import CommandRecord, ProjectResult, StageResult
from runner import resolve_executable

_STAGES = ("build", "lint", "tests", "coverage")
_HEADERS = ("Project", "Language", "Build", "Lint", "Tests", "Coverage")

_WARN_STATUSES = frozenset(
    {"no_linter_configured", "dependencies_missing", "tool_not_installed"}
)

# Higher number = worse.  Cells are compared by this rank.
_RANK = {"SKIP": 1, "PASS": 2, "WARN": 3, "TIMEOUT": 4, "FAIL": 5, "INTR": 6}


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _word(status: str) -> str:
    """Map a stage/command status to a cell word."""
    if status == "interrupted":
        return "INTR"
    if status == "fail":
        return "FAIL"
    if status == "timeout":
        return "TIMEOUT"
    if status in _WARN_STATUSES:
        return "WARN"
    if status == "pass":
        return "PASS"
    return "SKIP"


def cell_text(stage: StageResult) -> str:
    """Return the table cell for *stage* (worst status wins)."""
    words = [_word(stage.status)] + [_word(c.status) for c in stage.commands]
    worst = max(words, key=_RANK.__getitem__)
    if worst == "PASS" and stage.stage == "coverage" and stage.coverage_data is not None:
        lowest = stage.coverage_data.lowest_line_pct()
        return "WARN" if lowest is None else f"{lowest:.1f}%"
    return worst


def _stage_of(pr: ProjectResult, name: str) -> Optional[StageResult]:
    for s in pr.stages:
        if s.stage == name:
            return s
    return None


def _cells(pr: ProjectResult) -> list[str]:
    out = []
    for name in _STAGES:
        st = _stage_of(pr, name)
        out.append(cell_text(st) if st is not None else "SKIP")
    return out


def project_state(pr: ProjectResult) -> str:
    cells = _cells(pr)
    if any(c in ("FAIL", "TIMEOUT", "INTR") for c in cells):
        return "failed"
    if "WARN" in cells or pr.warnings:
        return "warnings"
    return "passed"


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _project_name(pr: ProjectResult, repo_root: Path) -> str:
    try:
        rel = pr.project.path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return pr.project.path.as_posix()
    return rel.as_posix() if rel.parts else "."


def _language(pr: ProjectResult) -> str:
    suffix = "" if pr.project.tested else " [untested]"
    return f"{pr.project.language}{suffix}"


def _join(cols: list[str], widths: list[int]) -> str:
    return "  ".join(c.ljust(w) for c, w in zip(cols, widths)).rstrip()


def _command_text(rec: CommandRecord) -> str:
    return " ".join(rec.command) if rec.command else ""


def _detail(pr: ProjectResult, st: StageResult, word: str) -> str:
    """Text after "<project> / <stage>: <WORD>  " for a non-pass cell."""
    if word == "WARN":
        if st.status == "no_linter_configured":
            return "no linter configured"
        for rec in st.commands:
            if rec.status == "tool_not_installed":
                return f"tool not installed: {rec.command[0] if rec.command else '?'}"
        if st.status == "dependencies_missing" or any(
            r.status == "dependencies_missing" for r in st.commands
        ):
            return "dependencies missing"
        return "no coverage data" if st.stage == "coverage" else st.status
    # FAIL / TIMEOUT / INTR: show the first command with that word
    for rec in st.commands:
        if _word(rec.status) == word:
            text = _command_text(rec)
            if rec.log_path:
                text += f"  (log: {rec.log_path})"
            return text
    return ""


def render_terminal(
    results: list[ProjectResult],
    repo_root: Path,
    *,
    verbose: bool = False,
) -> str:
    """Return the full terminal report for *results* (ends with a newline)."""
    rows = [
        [_project_name(pr, repo_root), _language(pr), *_cells(pr)] for pr in results
    ]
    widths = [
        max(len(_HEADERS[i]), *(len(r[i]) for r in rows)) if rows else len(_HEADERS[i])
        for i in range(len(_HEADERS))
    ]
    lines = [
        _join(list(_HEADERS), widths),
        "  ".join("-" * w for w in widths),
    ]
    lines += [_join(r, widths) for r in rows]

    sections: list[list[str]] = []

    if verbose:
        cmd_lines = ["Commands:"]
        for pr, row in zip(results, rows):
            for st in pr.stages:
                for rec in st.commands:
                    cmd_lines.append(
                        f"  {row[0]} / {st.stage}: {_word(rec.status)}  "
                        f"{_command_text(rec)}  ({rec.duration_s:.1f}s)"
                    )
        if len(cmd_lines) > 1:
            sections.append(cmd_lines)

    detail_lines = ["Details:"]
    for pr, row in zip(results, rows):
        for name in _STAGES:
            st = _stage_of(pr, name)
            if st is None:
                continue
            word = cell_text(st)
            if word in ("FAIL", "TIMEOUT", "INTR", "WARN"):
                detail_lines.append(
                    f"  {row[0]} / {name}: {word}  {_detail(pr, st, word)}".rstrip()
                )
    if len(detail_lines) > 1:
        sections.append(detail_lines)

    warn_lines = ["Warnings:"]
    for pr, row in zip(results, rows):
        for w in pr.warnings:
            warn_lines.append(f"  {row[0]}: {w}")
    if len(warn_lines) > 1:
        sections.append(warn_lines)

    for sec in sections:
        lines.append("")
        lines.extend(sec)

    states = [project_state(pr) for pr in results]
    n = len(results)
    noun = "project" if n == 1 else "projects"
    summary = (
        f"Summary: {n} {noun}: {states.count('passed')} passed, "
        f"{states.count('warnings')} with warnings, {states.count('failed')} failed"
    )
    if any(pr.interrupted for pr in results):
        summary += " (interrupted)"
    lines += ["", summary]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Environment block
# ---------------------------------------------------------------------------

_VERSION_ARGS: dict[str, list[str]] = {
    "go": ["version"],
    "java": ["-version"],
    "javac": ["-version"],
}
_WINDOWS_SUFFIXES = (".exe", ".cmd", ".bat")
_VERSION_TIMEOUT_S = 10
_VERSION_MAX_CHARS = 200


def _runner_name(exe: str) -> str:
    # Handle both separators so a Windows path is cut correctly on any OS.
    name = exe.replace("\\", "/").rsplit("/", 1)[-1]
    lower = name.lower()
    for suffix in _WINDOWS_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


def probe_version(exe: str, cwd: Path) -> Optional[str]:
    """Return the first line of ``<exe> --version``, or None if it fails."""
    args = [exe] + _VERSION_ARGS.get(_runner_name(exe).lower(), ["--version"])
    try:
        resolved = resolve_executable(args, cwd)
        if resolved is None:
            return None
        proc = subprocess.run(  # noqa: S603 - shell=False, version flag only
            resolved,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERSION_TIMEOUT_S,
            shell=False,
        )
    except Exception:  # noqa: BLE001 - never crash on a version probe
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip()
        if line:
            return line[:_VERSION_MAX_CHARS]
    return None


VersionFn = Callable[[str, Path], Optional[str]]


def collect_environment(
    results: list[ProjectResult],
    version_fn: VersionFn = probe_version,
    os_name: Optional[str] = None,
) -> dict:
    """Return ``{"os": ..., "runners": {name: version | "unknown"}}``."""
    if os_name is None:
        os_name = f"{platform.system()} {platform.release()}".strip() or "unknown"

    runners: dict[str, str] = {}
    for pr in results:
        for st in pr.stages:
            for rec in st.commands:
                if rec.status == "skipped" or not rec.command:
                    continue
                name = _runner_name(rec.command[0])
                if name in runners:
                    continue
                try:
                    version = version_fn(rec.command[0], pr.project.path)
                except Exception:  # noqa: BLE001
                    version = None
                runners[name] = version or "unknown"
    return {"os": os_name, "runners": runners}
