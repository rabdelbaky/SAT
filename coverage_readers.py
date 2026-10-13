"""Coverage readers for Pre-LLM Checks (Session 8).

Public API
----------
CoverageResult
    Coverage numbers for one tool's report file: line_pct, branch_pct (optional).

CoverageData
    All coverage results for one project after the Coverage stage has run.
    Holds per-tool results (never averaged) and warnings.

read_coverage_file(path) -> CoverageResult | None
    Parse *path* and return a CoverageResult.  Returns None on any error
    (sets no global state; caller interprets None as unreadable).

    Supported formats (auto-detected by filename):
      - JaCoCo XML   (jacoco.xml)          — xml.etree
      - Cobertura XML (coverage.xml, cobertura.xml, coverage.cobertura.xml)
                                           — xml.etree
      - Clover XML   (clover.xml, as written by PHPUnit `--coverage-clover`)
                                           — xml.etree
      - Istanbul json-summary
                     (coverage-summary.json) — json
      - lcov         (lcov.info, *.lcov)
      - Go cover profile (coverage.out, as written by
                       `go test -coverprofile`) — statement coverage, no branches

    A malformed or empty file → returns None (caller emits coverage_unreadable).

parse_coverage_from_output(text) -> float | None
    Scan command output for a coverage percentage line.
    Recognises patterns like:
      "TOTAL ... 85%"         (pytest-cov / coverage.py terminal report)
      "All files | 85.2"      (istanbul text summary)
      "coverage: 85.00% of statements" (go cover)
      "Lines:   85.0%"        (lcov genhtml summary)
      "TOTAL        100       15       85%"  (coverage.py)
    Returns the first match as a float (0-100).  Returns None if no match.

read_project_coverage(
    project_path, coverage_files, stage_start_time, output_texts
) -> CoverageData
    High-level entry point called by the orchestrator after the Coverage stage.

    For each path in *coverage_files*:
      - Skip (warn coverage_stale) if file mtime <= stage_start_time - 2s.
      - Attempt to parse with read_coverage_file.
      - On parse failure warn coverage_unreadable.
    If no file produced a result, try parse_coverage_from_output on each
    output text.
    If still nothing, warn coverage_missing.

    Several tools can produce results in the same project; all are kept
    separately in CoverageData.results (never averaged).
    The terminal table caller should show the lowest line_pct.

Rules (SPEC §3 step 9, §6):
- Freshness tolerance: 2 s (Windows filesystem timestamp resolution).
- No threshold in v1. Coverage never causes a fail by itself.
- A stale file → warning "coverage_stale", never a result.
- A malformed file → warning "coverage_unreadable", never a crash.
- No file, no output percentage → warning "coverage_missing".
- Line coverage is main; branch coverage included when the format provides it.
- Per-tool results are separate; never averaged.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

FRESHNESS_TOLERANCE_S: float = 2.0  # seconds; Windows filesystem resolution


@dataclass
class CoverageResult:
    """Coverage numbers for one tool's report file.

    Attributes
    ----------
    line_pct:
        Line coverage as a percentage (0.0–100.0).
    branch_pct:
        Branch coverage as a percentage (0.0–100.0), or None when the format
        does not provide it.
    source_file:
        The path that was read, as a string (for the report).
    format:
        A short label: "jacoco", "cobertura", "clover", "istanbul", "lcov",
        "gocover", "output".
    """

    line_pct: float
    branch_pct: Optional[float]
    source_file: str
    format: str


@dataclass
class CoverageData:
    """All coverage information collected for one project.

    Attributes
    ----------
    results:
        One CoverageResult per tool that reported successfully.  Never
        averaged: each tool's numbers are kept separately.
    warnings:
        Zero or more of: "coverage_stale", "coverage_unreadable",
        "coverage_missing".
    """

    results: list[CoverageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def lowest_line_pct(self) -> Optional[float]:
        """Return the lowest line_pct across all results, or None if empty."""
        if not self.results:
            return None
        return min(r.line_pct for r in self.results)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def _detect_format(path: Path) -> str:
    """Return a format label for *path* based on its name, or "unknown"."""
    name = path.name.lower()
    # Istanbul json-summary
    if name == "coverage-summary.json":
        return "istanbul"
    # lcov variants
    if name in ("lcov.info",) or name.endswith(".lcov"):
        return "lcov"
    # Go cover profile ("mode: set" header), written by `go test -coverprofile`
    if name == "coverage.out":
        return "gocover"
    # JaCoCo XML — identified by 'jacoco' in the filename
    if "jacoco" in name and name.endswith(".xml"):
        return "jacoco"
    # Clover XML — identified by 'clover' in the filename
    if "clover" in name and name.endswith(".xml"):
        return "clover"
    # Cobertura XML
    if name.endswith(".xml"):
        return "cobertura"
    # Ruby SimpleCov .resultset.json — not a standard format we parse
    return "unknown"


# ---------------------------------------------------------------------------
# Format readers
# ---------------------------------------------------------------------------


def _read_jacoco(path: Path) -> Optional[CoverageResult]:
    """Parse a JaCoCo XML report and return a CoverageResult, or None.

    JaCoCo XML structure (example):
        <report name="...">
          <counter type="LINE" missed="15" covered="85"/>
          <counter type="BRANCH" missed="5" covered="20"/>
          ...
        </report>

    We read the top-level <counter> elements on the <report> root for aggregate
    project totals.  Returns None on any parse error.
    """
    try:
        content = path.read_bytes()
        if not content.strip():
            return None
        root = ET.fromstring(content)
    except (ET.ParseError, OSError):
        return None

    line_pct: Optional[float] = None
    branch_pct: Optional[float] = None

    # Look for top-level counter elements on the report root
    for counter in root.findall("counter"):
        ctype = (counter.get("type") or "").upper()
        missed_str = counter.get("missed")
        covered_str = counter.get("covered")
        if missed_str is None or covered_str is None:
            continue
        try:
            missed = int(missed_str)
            covered = int(covered_str)
        except ValueError:
            continue
        total = missed + covered
        if total == 0:
            pct = 100.0
        else:
            pct = covered / total * 100.0

        if ctype == "LINE":
            line_pct = pct
        elif ctype == "BRANCH":
            branch_pct = pct

    if line_pct is None:
        return None

    return CoverageResult(
        line_pct=round(line_pct, 2),
        branch_pct=round(branch_pct, 2) if branch_pct is not None else None,
        source_file=str(path),
        format="jacoco",
    )


def _read_cobertura(path: Path) -> Optional[CoverageResult]:
    """Parse a Cobertura XML report and return a CoverageResult, or None.

    Cobertura XML structure (example):
        <coverage line-rate="0.85" branch-rate="0.75" ...>
          ...
        </coverage>

    The top-level <coverage> element carries aggregate rates as decimals.
    Returns None on any parse error.
    """
    try:
        content = path.read_bytes()
        if not content.strip():
            return None
        root = ET.fromstring(content)
    except (ET.ParseError, OSError):
        return None

    # The root element should be <coverage>; some tools nest under <coverages>
    cov_elem = root if root.tag == "coverage" else root.find(".//coverage")
    if cov_elem is None:
        return None

    line_rate = cov_elem.get("line-rate")
    branch_rate = cov_elem.get("branch-rate")

    # No coverable lines (tarpaulin writes lines-valid="0" line-rate="NaN"):
    # there is no percentage to report.
    if line_rate is None or cov_elem.get("lines-valid") == "0":
        return None

    try:
        line_pct = float(line_rate) * 100.0
    except ValueError:
        return None
    if not math.isfinite(line_pct):
        return None

    # No branches measured (tarpaulin: branches-valid="0" branch-rate="0"): no
    # branch percentage, not 0%.
    branch_pct: Optional[float] = None
    if branch_rate is not None and cov_elem.get("branches-valid") != "0":
        try:
            branch_pct = float(branch_rate) * 100.0
        except ValueError:
            pass
        if branch_pct is not None and not math.isfinite(branch_pct):
            branch_pct = None

    return CoverageResult(
        line_pct=round(line_pct, 2),
        branch_pct=round(branch_pct, 2) if branch_pct is not None else None,
        source_file=str(path),
        format="cobertura",
    )


def _read_clover(path: Path) -> Optional[CoverageResult]:
    """Parse a Clover XML report and return a CoverageResult, or None.

    Clover XML structure (as written by PHPUnit --coverage-clover):
        <coverage generated="...">
          <project timestamp="...">
            <file name="..."><metrics statements="4" .../></file>
            <metrics files="1" statements="4" coveredstatements="2"
                     conditionals="0" coveredconditionals="0" .../>
          </project>
        </coverage>

    The <metrics> directly under <project> holds the project totals (the
    per-file ones are ignored).  Line coverage is statement coverage.  Branch
    coverage only when conditionals > 0 (PHPUnit always writes 0).
    Returns None on any parse error or when there are no statements.
    """
    try:
        content = path.read_bytes()
        if not content.strip():
            return None
        root = ET.fromstring(content)
    except (ET.ParseError, OSError):
        return None

    if root.tag != "coverage":
        return None
    metrics = root.find("project/metrics")
    if metrics is None:
        return None

    try:
        statements = int(metrics.get("statements", ""))
        covered = int(metrics.get("coveredstatements", ""))
    except ValueError:
        return None
    if statements <= 0:
        return None
    line_pct = covered / statements * 100.0

    branch_pct: Optional[float] = None
    try:
        conditionals = int(metrics.get("conditionals", ""))
        covered_cond = int(metrics.get("coveredconditionals", ""))
    except ValueError:
        conditionals = 0
        covered_cond = 0
    if conditionals > 0:
        branch_pct = covered_cond / conditionals * 100.0

    return CoverageResult(
        line_pct=round(line_pct, 2),
        branch_pct=round(branch_pct, 2) if branch_pct is not None else None,
        source_file=str(path),
        format="clover",
    )


def _read_istanbul(path: Path) -> Optional[CoverageResult]:
    """Parse an Istanbul json-summary report and return a CoverageResult, or None.

    Istanbul json-summary structure:
        {
          "total": {
            "lines":      {"total": 100, "covered": 85, "skipped": 0, "pct": 85},
            "statements": {...},
            "branches":   {"total": 40, "covered": 30, "skipped": 0, "pct": 75},
            "functions":  {...}
          },
          "path/to/file.js": { ... }
        }

    We read the "total" key for aggregate coverage.
    Returns None on any parse error.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            return None
        data = json.loads(content)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    total = data.get("total")
    if not isinstance(total, dict):
        return None

    lines = total.get("lines")
    branches = total.get("branches")

    if not isinstance(lines, dict):
        return None

    line_pct_raw = lines.get("pct")
    if line_pct_raw is None:
        return None

    try:
        line_pct = float(line_pct_raw)
    except (ValueError, TypeError):
        return None

    branch_pct: Optional[float] = None
    if isinstance(branches, dict):
        branch_pct_raw = branches.get("pct")
        if branch_pct_raw is not None:
            try:
                branch_pct = float(branch_pct_raw)
            except (ValueError, TypeError):
                pass

    return CoverageResult(
        line_pct=round(line_pct, 2),
        branch_pct=round(branch_pct, 2) if branch_pct is not None else None,
        source_file=str(path),
        format="istanbul",
    )


def _read_lcov(path: Path) -> Optional[CoverageResult]:
    """Parse an lcov.info (or *.lcov) file and return a CoverageResult.

    lcov format (relevant lines):
        SF:<source file>
        DA:<line>,<hit count>
        ...
        end_of_record

    We count total DA lines and covered (hit count > 0) DA lines.
    Branch data (BRDA) is included when present.

    Returns None if no DA lines are found, or on read error.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            return None
    except OSError:
        return None

    total_lines = 0
    covered_lines = 0
    total_branches = 0
    covered_branches = 0
    has_branch_data = False

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("DA:"):
            # DA:<line_number>,<execution_count>
            parts = line[3:].split(",")
            if len(parts) < 2:
                continue
            try:
                count = int(parts[1])
            except ValueError:
                continue
            total_lines += 1
            if count > 0:
                covered_lines += 1
        elif line.startswith("BRDA:"):
            # BRDA:<line>,<block>,<branch>,<taken>  — taken is count or '-'
            has_branch_data = True
            parts = line[5:].split(",")
            if len(parts) < 4:
                continue
            taken = parts[3].strip()
            total_branches += 1
            if taken not in ("-", "0"):
                try:
                    if int(taken) > 0:
                        covered_branches += 1
                except ValueError:
                    pass

    if total_lines == 0:
        return None

    line_pct = covered_lines / total_lines * 100.0

    branch_pct: Optional[float] = None
    if has_branch_data and total_branches > 0:
        branch_pct = covered_branches / total_branches * 100.0

    return CoverageResult(
        line_pct=round(line_pct, 2),
        branch_pct=round(branch_pct, 2) if branch_pct is not None else None,
        source_file=str(path),
        format="lcov",
    )


def _read_gocover(path: Path) -> Optional[CoverageResult]:
    """Parse a Go cover profile and return a CoverageResult, or None.

    Format:
        mode: set|count|atomic
        <file>:<line>.<col>,<line>.<col> <statements> <count>

    Line coverage = statements in blocks with count > 0 / all statements.
    A block (same ``<file>:<range>``) can appear more than once, e.g. with
    ``-coverpkg``; like ``go tool cover`` it counts once, covered if any of
    its lines has count > 0.  Malformed block lines are skipped.  Returns
    None when the header is missing or no block line parses (e.g. a package
    without tests).
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines = content.splitlines()
    if not lines or not lines[0].startswith("mode:"):
        return None

    blocks: dict[str, tuple[int, bool]] = {}  # "<file>:<range>" -> (statements, covered)
    for line in lines[1:]:
        # "<file>:<range> <statements> <count>" — the file name may contain spaces
        parts = line.rsplit(" ", 2)
        if len(parts) != 3 or ":" not in parts[0]:
            continue
        try:
            statements = int(parts[1])
            count = int(parts[2])
        except ValueError:
            continue
        _, seen = blocks.get(parts[0], (statements, False))
        blocks[parts[0]] = (statements, seen or count > 0)

    total = sum(statements for statements, _ in blocks.values())
    covered = sum(statements for statements, hit in blocks.values() if hit)
    if total == 0:
        return None

    return CoverageResult(
        line_pct=round(covered / total * 100.0, 2),
        branch_pct=None,
        source_file=str(path),
        format="gocover",
    )


# ---------------------------------------------------------------------------
# Public: parse one file
# ---------------------------------------------------------------------------


def read_coverage_file(path: Path) -> Optional[CoverageResult]:
    """Parse *path* and return a CoverageResult, or None on any error.

    Format is auto-detected from the filename.  An unknown format returns
    None without raising.  A malformed or empty file also returns None.
    """
    fmt = _detect_format(path)
    try:
        if fmt == "jacoco":
            return _read_jacoco(path)
        if fmt == "cobertura":
            return _read_cobertura(path)
        if fmt == "clover":
            return _read_clover(path)
        if fmt == "istanbul":
            return _read_istanbul(path)
        if fmt == "lcov":
            return _read_lcov(path)
        if fmt == "gocover":
            return _read_gocover(path)
        # Unknown format: not a crash, just None
        return None
    except Exception:  # noqa: BLE001 – never crash on a file
        return None


# ---------------------------------------------------------------------------
# Public: parse percentage from command output
# ---------------------------------------------------------------------------

# Patterns tried in order; the first match wins.  Each must produce exactly
# one capture group that is the numeric percentage value.
_OUTPUT_PATTERNS: list[re.Pattern[str]] = [
    # pytest-cov / coverage.py: "TOTAL   100   15   85%"
    re.compile(r"^TOTAL\s+.*?\s(\d+(?:\.\d+)?)%", re.MULTILINE),
    # Istanbul text summary: "All files | 85.20 | ..."
    re.compile(r"All\s+files\s*\|\s*(\d+(?:\.\d+)?)", re.MULTILINE),
    # Go cover: "coverage: 85.3% of statements"
    re.compile(r"coverage:\s*(\d+(?:\.\d+)?)%\s+of\s+statements", re.MULTILINE),
    # lcov genhtml: "  lines......: 85.0% (170 of 200 lines)"
    re.compile(r"lines\.+:\s*(\d+(?:\.\d+)?)%", re.MULTILINE),
    # Generic "Lines: 85.0%" (some Cobertura text summaries)
    re.compile(r"Lines\s*:\s*(\d+(?:\.\d+)?)%", re.MULTILINE | re.IGNORECASE),
    # Generic last-resort: any line ending in " 85%" or " 85.2%"
    re.compile(r"\b(\d+(?:\.\d+)?)%\s*$", re.MULTILINE),
]


def parse_coverage_from_output(text: str) -> Optional[float]:
    """Return the first coverage percentage found in *text*, or None.

    Scans *text* for lines matching known coverage output patterns.
    Returns a float in [0.0, 100.0], or None if nothing matches.
    """
    for pattern in _OUTPUT_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                value = float(m.group(1))
                if 0.0 <= value <= 100.0:
                    return value
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Public: project-level coverage collection
# ---------------------------------------------------------------------------


def read_project_coverage(
    project_path: Path,
    coverage_files: list[str],
    stage_start_time: float,
    output_texts: list[str],
) -> CoverageData:
    """Collect coverage data for one project after the Coverage stage.

    Parameters
    ----------
    project_path:
        Absolute path to the project folder.
    coverage_files:
        List of relative file paths (from languages.toml ``coverage_files``).
        May contain glob-like names (e.g. "*.lcov") — we do a simple glob
        within the project folder.
    stage_start_time:
        ``time.time()`` recorded immediately before the Coverage stage command
        was launched.  Files whose mtime is <= (stage_start_time - TOLERANCE)
        are considered stale.
    output_texts:
        The combined stdout+stderr output from every Coverage stage command,
        as plain strings (one entry per command).  Used as fallback when no
        file is found or all files are stale/unreadable.

    Returns
    -------
    CoverageData
        Always returns a CoverageData (never raises).  Warnings are
        accumulated inside the object.
    """
    data = CoverageData()
    stale_threshold = stage_start_time - FRESHNESS_TOLERANCE_S

    for rel_pattern in coverage_files:
        # Resolve glob-style patterns (e.g. "*.lcov", "*.xcodeproj")
        candidate_paths: list[Path] = []
        if "*" in rel_pattern:
            candidate_paths = list(project_path.glob(rel_pattern))
        else:
            p = project_path / rel_pattern
            if p.exists():
                candidate_paths = [p]

        for candidate in candidate_paths:
            if not candidate.is_file():
                continue

            # Files in a format we do not parse (e.g. Python's binary
            # .coverage database) are not coverage reports for our purposes:
            # skip them silently instead of warning stale/unreadable.
            if _detect_format(candidate) == "unknown":
                continue

            # Freshness check
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue

            if mtime <= stale_threshold:
                # File exists but is older than the stage start — stale
                if "coverage_stale" not in data.warnings:
                    data.warnings.append("coverage_stale")
                continue

            # Attempt to parse
            result = read_coverage_file(candidate)
            if result is None:
                if "coverage_unreadable" not in data.warnings:
                    data.warnings.append("coverage_unreadable")
                continue

            data.results.append(result)

    # Fallback: try parsing a percentage from command output
    if not data.results:
        for output_text in output_texts:
            pct = parse_coverage_from_output(output_text)
            if pct is not None:
                data.results.append(
                    CoverageResult(
                        line_pct=pct,
                        branch_pct=None,
                        source_file="<output>",
                        format="output",
                    )
                )
                break  # one output-based result is enough

    # If still nothing, emit coverage_missing
    if not data.results:
        if "coverage_missing" not in data.warnings:
            data.warnings.append("coverage_missing")

    return data
