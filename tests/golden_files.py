"""Golden-file compare shared by test_fake_runs.py and test_report_schema.py.

check_golden(path, actual, mismatch_message)
    UPDATE_GOLDEN=1 set: write *actual* to *path* and pass.
    Golden file missing:  fail (never created silently).
    Different:            fail with *mismatch_message* and a unified diff.

Files are written with "\\n" line endings and read back with universal
newlines, so a golden file made on Windows matches on macOS/Linux.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"

MISSING_MESSAGE = "golden file missing: run with UPDATE_GOLDEN=1, review, commit"


def updating() -> bool:
    return os.environ.get("UPDATE_GOLDEN") == "1"


def check_golden(path: Path, actual: str, mismatch_message: str) -> None:
    if updating():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
        return
    if not path.is_file():
        pytest.fail(f"{MISSING_MESSAGE} ({path.name})", pytrace=False)
    expected = path.read_text(encoding="utf-8")
    if expected == actual:
        return
    diff = "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"tests/golden/{path.name}",
            tofile="actual",
        )
    )
    pytest.fail(f"{mismatch_message}\n{diff}", pytrace=False)
