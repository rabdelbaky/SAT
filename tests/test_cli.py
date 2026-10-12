"""Black-box CLI tests (seam: subprocess invocation of pre_llm_checks.py).

Also tests parse_duration() as a pure-function unit seam.
"""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

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
    combined = result.stdout + result.stderr
    assert any(c.isdigit() for c in combined), (
        f"No version digits in output: {combined!r}"
    )


# ---------------------------------------------------------------------------
# Cycle 2: --dry-run on empty folder exits 3
# ---------------------------------------------------------------------------


def test_dry_run_empty_folder_exits_3():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--dry-run")
    assert result.returncode == 3


# ---------------------------------------------------------------------------
# Cycle 3: trust notice — stderr, first output, names the resolved folder
# ---------------------------------------------------------------------------


def test_trust_notice_goes_to_stderr_not_stdout():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--dry-run")
    # stdout must be empty (only table/report go there; nothing yet for empty folder)
    assert result.stdout == "", f"stdout should be empty but got: {result.stdout!r}"
    assert "NOTICE" in result.stderr, f"NOTICE not found in stderr: {result.stderr!r}"


def test_trust_notice_is_first_line_on_stderr():
    with tempfile.TemporaryDirectory() as tmp:
        resolved = str(Path(tmp).resolve())
        result = run("--path", tmp, "--dry-run")
    lines = [l for l in result.stderr.splitlines() if l.strip()]
    assert lines, "No stderr output at all"
    assert lines[0].startswith("NOTICE:"), (
        f"First stderr line is not NOTICE: {lines[0]!r}"
    )


def test_trust_notice_contains_resolved_path():
    with tempfile.TemporaryDirectory() as tmp:
        resolved = str(Path(tmp).resolve())
        result = run("--path", tmp, "--dry-run")
    assert resolved in result.stderr, (
        f"Resolved path {resolved!r} not found in stderr:\n{result.stderr}"
    )


def test_trust_notice_mentions_trust():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--dry-run")
    assert "trust" in result.stderr.lower(), (
        f"Word 'trust' not found in stderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Cycle 4: --path validation — non-existent path
# ---------------------------------------------------------------------------


def test_nonexistent_path_exits_2():
    result = run("--path", "/nonexistent/path/xyz123")
    assert result.returncode == 2


def test_nonexistent_path_prints_one_error_line_to_stderr():
    result = run("--path", "/nonexistent/path/xyz123")
    error_lines = [l for l in result.stderr.splitlines() if l.strip()]
    # Filter out the NOTICE line — only count ERROR lines
    error_lines = [l for l in error_lines if not l.startswith("NOTICE")]
    assert len(error_lines) == 1, (
        f"Expected 1 error line (excluding NOTICE), got {len(error_lines)}:\n{result.stderr}"
    )
    assert error_lines[0].startswith("ERROR:"), (
        f"Error line does not start with 'ERROR:': {error_lines[0]!r}"
    )


def test_nonexistent_path_no_traceback():
    result = run("--path", "/nonexistent/path/xyz123")
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_nonexistent_path_nothing_on_stdout():
    result = run("--path", "/nonexistent/path/xyz123")
    assert result.stdout == "", f"stdout should be empty, got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# Cycle 5: --path is a file, not a folder
# ---------------------------------------------------------------------------


def test_path_is_file_exits_2():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        fpath = f.name
    try:
        result = run("--path", fpath)
        assert result.returncode == 2
    finally:
        Path(fpath).unlink(missing_ok=True)


def test_path_is_file_prints_one_error_line_to_stderr():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        fpath = f.name
    try:
        result = run("--path", fpath)
        error_lines = [
            l
            for l in result.stderr.splitlines()
            if l.strip() and not l.startswith("NOTICE")
        ]
        assert len(error_lines) == 1, (
            f"Expected 1 error line, got {len(error_lines)}:\n{result.stderr}"
        )
        assert error_lines[0].startswith("ERROR:"), (
            f"Error line does not start with 'ERROR:': {error_lines[0]!r}"
        )
    finally:
        Path(fpath).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Cycle 6: --path not readable (Unix only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
def test_unreadable_path_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        locked = Path(tmp) / "locked"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            result = run("--path", str(locked))
            assert result.returncode == 2
        finally:
            locked.chmod(0o755)


@pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
def test_unreadable_path_prints_one_error_line_to_stderr():
    with tempfile.TemporaryDirectory() as tmp:
        locked = Path(tmp) / "locked"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            result = run("--path", str(locked))
            error_lines = [
                l
                for l in result.stderr.splitlines()
                if l.strip() and not l.startswith("NOTICE")
            ]
            assert len(error_lines) == 1, (
                f"Expected 1 error line, got {len(error_lines)}:\n{result.stderr}"
            )
            assert error_lines[0].startswith("ERROR:"), (
                f"Error line does not start with 'ERROR:': {error_lines[0]!r}"
            )
        finally:
            locked.chmod(0o755)


# ---------------------------------------------------------------------------
# Cycle 7: invalid / unknown flags → exit 2, one-line error on stderr, no traceback
# ---------------------------------------------------------------------------


def test_unknown_flag_exits_2():
    result = run("--no-such-flag")
    assert result.returncode == 2


def test_unknown_flag_prints_error_to_stderr():
    result = run("--no-such-flag")
    assert result.stderr.strip() != "", "stderr should not be empty for unknown flag"


def test_unknown_flag_no_traceback():
    result = run("--no-such-flag")
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_unknown_flag_nothing_on_stdout():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--no-such-flag")
    assert result.stdout == "", f"stdout should be empty, got: {result.stdout!r}"


# ---------------------------------------------------------------------------
# Cycle 8: parse_duration unit tests (pure-function seam)
# ---------------------------------------------------------------------------

# Import parse_duration directly for unit testing
import importlib.util

_spec = importlib.util.spec_from_file_location("pre_llm_checks", SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
parse_duration = _mod.parse_duration


@pytest.mark.parametrize(
    "value,expected",
    [
        ("90s", 90),
        ("30m", 1800),
        ("1h", 3600),
        ("1h30m", 5400),
        ("600", 600),
        ("0s", 0),
        ("2h", 7200),
        ("45m", 2700),
        ("1h1m", 3660),
    ],
)
def test_parse_duration_valid(value, expected):
    assert parse_duration(value) == expected, (
        f"parse_duration({value!r}) = {parse_duration(value)}, expected {expected}"
    )


@pytest.mark.parametrize(
    "bad_value",
    [
        "abc",
        "1x",
        "",
        "1h30",  # trailing digits without unit
        "ms",
        "-1",
        "1.5h",
        "1h2h",
    ],
)
def test_parse_duration_invalid_raises(bad_value):
    with pytest.raises(ValueError):
        parse_duration(bad_value)


# ---------------------------------------------------------------------------
# Cycle 9: --timeout-* bad value → one-line error on stderr, exit 2
# ---------------------------------------------------------------------------


def test_bad_timeout_build_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-build", "notatime")
    assert result.returncode == 2


def test_bad_timeout_build_single_error_line_on_stderr():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-build", "notatime")
    error_lines = [
        l
        for l in result.stderr.splitlines()
        if l.strip() and not l.startswith("NOTICE")
    ]
    assert len(error_lines) == 1, (
        f"Expected 1 error line, got {len(error_lines)}:\n{result.stderr}"
    )
    assert error_lines[0].startswith("ERROR:"), (
        f"Error line does not start with 'ERROR:': {error_lines[0]!r}"
    )


def test_bad_timeout_build_no_traceback():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-build", "notatime")
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_bad_timeout_lint_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-lint", "1x")
    assert result.returncode == 2


def test_bad_timeout_tests_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-tests", "bad")
    assert result.returncode == 2


def test_bad_timeout_coverage_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-coverage", "1h2h")
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Cycle 10: valid --timeout-* values are accepted
# ---------------------------------------------------------------------------


def test_valid_timeout_seconds_accepted():
    # Plain integer seconds: should not cause exit 2
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-build", "600")
    # exit 3 (no projects) is fine — exit 2 would indicate a parse error
    assert result.returncode != 2, f"Valid timeout '600' rejected: {result.stderr}"


def test_valid_timeout_duration_format_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-build", "10m")
    assert result.returncode != 2, f"Valid timeout '10m' rejected: {result.stderr}"


def test_valid_timeout_compound_format_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--timeout-build", "1h30m")
    assert result.returncode != 2, f"Valid timeout '1h30m' rejected: {result.stderr}"


# ---------------------------------------------------------------------------
# Cycle 11: all SPEC §11 flags exist (parse without error; no traceback)
# ---------------------------------------------------------------------------


def test_all_spec_flags_parse_without_traceback():
    """Every flag in SPEC §11 must be accepted by the parser."""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            "--path",
            tmp,
            "--output",
            "out.json",
            "--dry-run",
            "--steps",
            "build,lint",
            "--lint-anyway",
            "--verbose",
            "--timeout-build",
            "10m",
            "--timeout-lint",
            "5m",
            "--timeout-tests",
            "15m",
            "--timeout-coverage",
            "15m",
            "--tail-lines",
            "50",
            "--config",
            "pre-llm.toml",
            "--add-gitignore",
        )
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
    # exit 3 (no projects) or 0 are the only acceptable codes here
    assert result.returncode in (0, 3), (
        f"Unexpected exit code {result.returncode}; stderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Cycle 12: missing languages.toml → exit 2, one-line ERROR, no traceback
# (pre-existing tests kept and preserved)
# ---------------------------------------------------------------------------


def _run_with_languages_toml(languages_toml_path):
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
        # Filter out NOTICE line
        error_lines = [l for l in error_lines if not l.startswith("NOTICE")]
        assert len(error_lines) == 1, f"Expected 1 error line, got: {result.stderr!r}"
        assert error_lines[0].startswith("ERROR:")
    finally:
        bad_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Cycle 13: unknown --steps name → exit 2, one-line ERROR, before --dry-run
# ---------------------------------------------------------------------------


def test_unknown_step_exits_2_even_with_dry_run():
    # An empty folder would exit 3; exit 2 proves the check runs before scanning.
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--dry-run", "--steps", "build,bogus")
    assert result.returncode == 2


def test_unknown_step_prints_named_error_to_stderr():
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, "--steps", "build,bogus")
    assert "ERROR: unknown step: bogus" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# Cycle 14: --tail-lines below 1 → exit 2, one-line ERROR, no traceback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["0", "-5"])
def test_tail_lines_below_one_rejected_with_one_error_line(bad_value):
    with tempfile.TemporaryDirectory() as tmp:
        result = run("--path", tmp, f"--tail-lines={bad_value}")
    assert result.returncode == 2
    error_lines = [
        l
        for l in result.stderr.splitlines()
        if l.strip() and not l.startswith("NOTICE")
    ]
    assert len(error_lines) == 1, f"Expected 1 error line, got:\n{result.stderr}"
    assert error_lines[0].startswith("ERROR:")
    assert "Traceback" not in result.stderr
