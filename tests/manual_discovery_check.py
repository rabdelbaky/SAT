"""Manual discovery checks for Session 4.

Run:   python tests/manual_discovery_check.py
Each check prints PASS or FAIL with a short reason.
Exit code: 0 if all pass, 1 if any fail.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from discovery import discover_projects
from pre_llm_checks import load_languages

FIXTURE = Path(__file__).parent / "fixtures" / "monorepo"
SCRIPT = Path(__file__).parent.parent / "pre_llm_checks.py"
LANGUAGES = load_languages()

_failures: list[str] = []


def check(name: str, passed: bool, reason: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    detail = f"  ({reason})" if reason else ""
    print(f"{status}  {name}{detail}")
    if not passed:
        _failures.append(name)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _by_path(projects, rel: str):
    target = (FIXTURE / rel).resolve() if rel != "." else FIXTURE.resolve()
    for p in projects:
        if p.path.resolve() == target:
            return p
    return None


def _run_dry_run(path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--path", path, "--dry-run"],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Check 1: five projects found in monorepo fixture
# ---------------------------------------------------------------------------

projects = discover_projects(FIXTURE, LANGUAGES)
check(
    "monorepo: five projects found",
    len(projects) == 5,
    f"got {len(projects)}: {[str(p.path) for p in projects]}",
)

# ---------------------------------------------------------------------------
# Check 2: node_modules not traversed
# ---------------------------------------------------------------------------

leaked = [p for p in projects if "node_modules" in p.path.parts]
check("monorepo: node_modules skipped", len(leaked) == 0, str(leaked))

# ---------------------------------------------------------------------------
# Check 3: build/ not traversed
# ---------------------------------------------------------------------------

leaked = [p for p in projects if "build" in p.path.parts]
check("monorepo: build/ skipped", len(leaked) == 0, str(leaked))

# ---------------------------------------------------------------------------
# Check 4: .git not traversed
# ---------------------------------------------------------------------------

leaked = [p for p in projects if ".git" in p.path.parts]
check("monorepo: .git skipped", len(leaked) == 0, str(leaked))

# ---------------------------------------------------------------------------
# Check 5: root JS project found
# ---------------------------------------------------------------------------

root_proj = _by_path(projects, ".")
check("monorepo: root javascript project found", root_proj is not None)
if root_proj:
    check(
        "monorepo: root project language is javascript",
        root_proj.language == "javascript",
        f"got {root_proj.language!r}",
    )

# ---------------------------------------------------------------------------
# Check 6: packages/api JS sub-project found
# ---------------------------------------------------------------------------

api = _by_path(projects, "packages/api")
check("monorepo: packages/api found", api is not None)
if api:
    check(
        "monorepo: packages/api is javascript",
        api.language == "javascript",
        f"got {api.language!r}",
    )

# ---------------------------------------------------------------------------
# Check 7: packages/ui JS sub-project found
# ---------------------------------------------------------------------------

ui = _by_path(projects, "packages/ui")
check("monorepo: packages/ui found", ui is not None)

# ---------------------------------------------------------------------------
# Check 8: services/worker Go project found
# ---------------------------------------------------------------------------

worker = _by_path(projects, "services/worker")
check("monorepo: services/worker found", worker is not None)
if worker:
    check(
        "monorepo: services/worker is go",
        worker.language == "go",
        f"got {worker.language!r}",
    )
    check(
        "monorepo: services/worker build_files contains go.mod",
        "go.mod" in worker.build_files,
        str(worker.build_files),
    )

# ---------------------------------------------------------------------------
# Check 9: services/ml Python project — one project, both build files listed
# ---------------------------------------------------------------------------

ml = _by_path(projects, "services/ml")
check("monorepo: services/ml found", ml is not None)
if ml:
    check(
        "monorepo: services/ml is python",
        ml.language == "python",
        f"got {ml.language!r}",
    )
    check(
        "monorepo: services/ml build_files has pyproject.toml",
        "pyproject.toml" in ml.build_files,
        str(ml.build_files),
    )
    check(
        "monorepo: services/ml build_files has requirements.txt",
        "requirements.txt" in ml.build_files,
        str(ml.build_files),
    )
    check(
        "monorepo: services/ml primary_build_file is pyproject.toml",
        ml.primary_build_file == "pyproject.toml",
        f"got {ml.primary_build_file!r}",
    )

# ---------------------------------------------------------------------------
# Check 10: only ONE python project at services/ml (not two)
# ---------------------------------------------------------------------------

ml_projects = [
    p
    for p in projects
    if p.language == "python"
    and p.path.resolve() == (FIXTURE / "services" / "ml").resolve()
]
check(
    "monorepo: exactly one python project at services/ml",
    len(ml_projects) == 1,
    f"got {len(ml_projects)}",
)

# ---------------------------------------------------------------------------
# Check 11: only python, javascript, java, kotlin, go, csharp and ruby projects are tested
# ---------------------------------------------------------------------------

_TESTED = ("python", "javascript", "java", "kotlin", "go", "csharp", "ruby")
wrong_tested = [p for p in projects if p.tested != (p.language in _TESTED)]
check(
    "monorepo: only python, javascript, java, kotlin, go, csharp and ruby projects are tested",
    not wrong_tested,
    f"wrong tested flag: {[(str(p.path), p.language, p.tested) for p in wrong_tested]}",
)

# ---------------------------------------------------------------------------
# Check 12: empty folder returns empty list, exit 3
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", tmp, "--dry-run"],
        capture_output=True,
        text=True,
    )
check(
    "empty folder: exit code 3",
    result.returncode == 3,
    f"got exit code {result.returncode}",
)
check(
    "empty folder: 'No supported projects found.' on stderr",
    "No supported projects found." in result.stderr,
    f"stderr was: {result.stderr!r}",
)

# ---------------------------------------------------------------------------
# Check 13: --dry-run on monorepo prints five lines (one per project)
# ---------------------------------------------------------------------------

dry = _run_dry_run(str(FIXTURE))
# Count non-empty stdout lines that are project headers (not indented detail lines).
# Session 5 adds indented command/skipped lines; we only count project headers.
output_lines = [
    l for l in dry.stdout.splitlines() if l.strip() and not l.startswith(" ")
]
check(
    "monorepo --dry-run: five output lines",
    len(output_lines) == 5,
    f"got {len(output_lines)}: {output_lines}",
)

# ---------------------------------------------------------------------------
# Check 14: --dry-run lines contain [untested] except python, javascript, java, kotlin, go, csharp and ruby
# (tested)
# ---------------------------------------------------------------------------

labels_ok = all(
    ("[untested]" in line)
    == (not any(f" {lang} " in line for lang in _TESTED))
    for line in output_lines
)
check(
    "monorepo --dry-run: [untested] on every line except python, javascript, java, kotlin, go, csharp and ruby",
    labels_ok,
    f"lines: {output_lines}",
)

# ---------------------------------------------------------------------------
# Check 15: --dry-run exit code is 0
# ---------------------------------------------------------------------------

check(
    "monorepo --dry-run: exit code 0",
    dry.returncode == 0,
    f"got {dry.returncode}; stderr: {dry.stderr!r}",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = 15 + (4 if root_proj else 0)  # dynamic checks for sub-fields
print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
