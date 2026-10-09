"""Black-box CLI tests (seam: subprocess invocation of pre_llm_checks.py)."""

import subprocess
import sys
import os
import tempfile
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "pre_llm_checks.py"


def run(*args, cwd=None, env=None):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or Path(__file__).parent.parent,
        env=env,
    )
    return result


# ---------------------------------------------------------------------------
# Cycle 1: --version
# ---------------------------------------------------------------------------


def test_version_exits_0():
    result = run("--version")
    assert result.returncode == 0


def test_version_prints_version_string():
    result = run("--version")
    # Output must contain a version number like 1.0 or 0.1.0 etc.
    combined = result.stdout + result.stderr
    assert any(c.isdigit() for c in combined), (
        f"No version digits in output: {combined!r}"
    )


# ---------------------------------------------------------------------------
# Cycle 2: --dry-run on empty folder exits 3, trust notice printed first
# ---------------------------------------------------------------------------


def test_dry_run_empty_folder_exits_3():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--dry-run")
    assert result.returncode == 3


def test_dry_run_trust_notice_printed_before_anything_else():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--dry-run")
    combined = result.stdout + result.stderr
    # Trust notice must appear; it must be the first non-empty line
    lines = [l for l in combined.splitlines() if l.strip()]
    assert lines, "No output at all"
    first = lines[0].lower()
    assert (
        "trust" in first or "script" in first or "execute" in first or "run" in first
    ), f"First output line doesn't look like a trust notice: {lines[0]!r}"


# ---------------------------------------------------------------------------
# Cycle 4: missing / malformed languages.toml → exit 2, one-line error, no traceback
# ---------------------------------------------------------------------------


def _run_with_languages_toml(languages_toml_path):
    """Run the CLI pointing LANGUAGES_TOML at an arbitrary path."""
    import os

    env = os.environ.copy()
    env["PRE_LLM_LANGUAGES_TOML"] = str(languages_toml_path)
    with tempfile.TemporaryDirectory() as tmp:
        return run("--path", tmp, "--dry-run", env=env)


def test_missing_languages_toml_exits_2():
    result = _run_with_languages_toml(Path("/nonexistent/languages.toml"))
    assert result.returncode == 2


def test_missing_languages_toml_prints_error_to_stderr():
    result = _run_with_languages_toml(Path("/nonexistent/languages.toml"))
    assert "ERROR" in result.stderr
    assert (
        "languages.toml" in result.stderr.lower()
        or "cannot read" in result.stderr.lower()
    )


def test_missing_languages_toml_no_traceback():
    result = _run_with_languages_toml(Path("/nonexistent/languages.toml"))
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_malformed_languages_toml_exits_2():
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write("this is not [ valid toml !!!")
        bad_path = Path(f.name)
    try:
        result = _run_with_languages_toml(bad_path)
        assert result.returncode == 2
    finally:
        bad_path.unlink(missing_ok=True)


def test_malformed_languages_toml_prints_single_error_line():
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write("this is not [ valid toml !!!")
        bad_path = Path(f.name)
    try:
        result = _run_with_languages_toml(bad_path)
        error_lines = [l for l in result.stderr.splitlines() if l.strip()]
        assert len(error_lines) == 1, f"Expected 1 error line, got: {result.stderr!r}"
        assert error_lines[0].startswith("ERROR:")
    finally:
        bad_path.unlink(missing_ok=True)
