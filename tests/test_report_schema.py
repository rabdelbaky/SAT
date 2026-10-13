"""Report shape guard (Session 21).

Seam: build_report(...) + write_report(...) on hand-made data that fills every
field.  The report is turned into a sorted list of key paths (keys only, no
values; a list adds "[]"; the runner names under environment.runners are data,
shown as <name>) and compared with tests/golden/report_schema_<version>.txt.

Any change to the shape must bump _REPORT_SCHEMA_VERSION in pre_llm_checks.py,
regenerate the golden file with UPDATE_GOLDEN=1, and update README.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from golden_files import GOLDEN_DIR, check_golden
from pre_llm_checks import _REPORT_SCHEMA_VERSION, build_report, write_report

_ROOT = Path("/repo")

# Objects whose keys are data (runner names), not part of the shape.
_MAP_PATHS = {"environment.runners"}

_MISMATCH = (
    "report shape changed: bump _REPORT_SCHEMA_VERSION in pre_llm_checks.py, "
    "regenerate with UPDATE_GOLDEN=1, and update README.md"
)


def _full_projects_data() -> list[dict]:
    """One project that uses every field build_report knows about."""
    return [
        {
            "path": _ROOT / "backend",
            "language": "python",
            "build_files": ["backend/pyproject.toml", "backend/requirements.txt"],
            "skipped_scripts": [{"name": "lint:fix", "reason": "fixer"}],
            "warnings": ["coverage_stale"],
            "coverage": {
                "results": [
                    {
                        "line_pct": 72.0,
                        "branch_pct": 50.0,
                        "source_file": "backend/coverage.xml",
                        "format": "cobertura",
                    }
                ],
                "lowest_line_pct": 72.0,
                "warnings": ["coverage_stale"],
            },
            "commands": [
                {
                    "command": ["pytest", "-q"],
                    "scripts": ["test"],
                    "source": "builtin",
                    "status": "fail",
                    "duration_s": 1.5,
                    "output_tail": ["1 failed"],
                    "log_path": _ROOT / ".pre-llm/logs/backend/tests-0.log",
                    "findings": [
                        {
                            "file": "backend/test_calc.py",
                            "line": 3,
                            "rule": "assert",
                            "severity": "error",
                            "message": "assert 1 == 2",
                        }
                    ],
                    "stage": "tests",
                    "reason": "build_gate",
                }
            ],
        }
    ]


def _full_report(tmp_path: Path) -> dict:
    report = build_report(
        _full_projects_data(),
        _ROOT,
        tail_lines=50,
        status="fail",
        environment={"os": "Linux 6.1", "runners": {"pytest": "pytest 8.3.0"}},
        warnings=["gitignore_missing"],
        counts={"pass": 2, "fail": 1, "timeout": 0, "warning": 1, "skipped": 0, "interrupted": 0},
        generated_at="2026-10-13T13:10:14+00:00",
    )
    # A 1-byte cap forces the trimmed shape, so "truncated" is covered too.
    out = tmp_path / "report.json"
    write_report(report, out, size_cap_bytes=1)
    return json.loads(out.read_text(encoding="utf-8"))


def _key_paths(value, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        if prefix in _MAP_PATHS:
            paths.add(f"{prefix}.<name>")
            return paths
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(child, list):
                path += "[]"
            paths.add(path)
            paths |= _key_paths(child, path)
    elif isinstance(value, list):
        for item in value:
            paths |= _key_paths(item, prefix)
    return paths


def test_report_shape_matches_golden(tmp_path):
    shape = "\n".join(sorted(_key_paths(_full_report(tmp_path)))) + "\n"
    check_golden(GOLDEN_DIR / f"report_schema_{_REPORT_SCHEMA_VERSION}.txt", shape, _MISMATCH)


def test_full_report_fills_every_optional_field(tmp_path):
    """Guard against a vacuous golden file: the optional fields are really there."""
    shape = _key_paths(_full_report(tmp_path))
    for path in (
        "summary.counts.pass",
        "summary.generated_at",
        "environment.runners.<name>",
        "truncated",
        "projects[].warnings[]",
        "projects[].coverage.results[].line_pct",
        "projects[].skipped_scripts[].reason",
        "projects[].commands[].reason",
        "projects[].commands[].findings[].message",
        "projects[].commands[].findings_total",
    ):
        assert path in shape, path
