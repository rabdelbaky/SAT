"""Manual smoke-checks for CLI argument parsing, path validation, trust notice.

Run:  python tests/manual_cli_check.py

Each check prints "PASS <name>" or "FAIL <name>: <reason>".
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SCRIPT = Path(__file__).parent.parent / "pre_llm_checks.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass(name: str) -> None:
    print(f"PASS {name}")


def _fail(name: str, reason: str) -> None:
    print(f"FAIL {name}: {reason}")


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
        env=env,
    )


def _run_with_tmp(*args, env=None):
    """Run with a fresh temporary directory as --path."""
    with tempfile.TemporaryDirectory() as tmp:
        result = _run("--path", tmp, *args, env=env)
        # Store resolved path for callers that need it
        result._tmp_resolved = str(Path(tmp).resolve())
    return result


# ---------------------------------------------------------------------------
# Check 1 — trust notice goes to stderr, not stdout
# ---------------------------------------------------------------------------


def check_1_trust_notice_on_stderr() -> None:
    name = "1_trust_notice_on_stderr"
    try:
        result = _run_with_tmp("--dry-run")
        if result.stdout != "":
            _fail(name, f"stdout is not empty: {result.stdout!r}")
            return
        if "NOTICE" not in result.stderr:
            _fail(name, f"NOTICE not found in stderr: {result.stderr!r}")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 2 — trust notice is the first line of stderr
# ---------------------------------------------------------------------------


def check_2_trust_notice_is_first_stderr_line() -> None:
    name = "2_trust_notice_first_line"
    try:
        result = _run_with_tmp("--dry-run")
        lines = [l for l in result.stderr.splitlines() if l.strip()]
        if not lines:
            _fail(name, "stderr is empty")
            return
        if not lines[0].startswith("NOTICE:"):
            _fail(name, f"first stderr line is {lines[0]!r}, expected 'NOTICE: …'")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 3 — trust notice contains the resolved absolute folder path
# ---------------------------------------------------------------------------


def check_3_trust_notice_contains_resolved_path() -> None:
    name = "3_trust_notice_contains_resolved_path"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            resolved = str(Path(tmp).resolve())
            result = _run("--path", tmp, "--dry-run")
        if resolved not in result.stderr:
            _fail(
                name,
                f"resolved path {resolved!r} not found in stderr:\n{result.stderr}",
            )
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 4 — trust notice mentions "trust"
# ---------------------------------------------------------------------------


def check_4_trust_notice_mentions_trust() -> None:
    name = "4_trust_notice_mentions_trust"
    try:
        result = _run_with_tmp("--dry-run")
        if "trust" not in result.stderr.lower():
            _fail(name, f"word 'trust' not in stderr: {result.stderr!r}")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 5 — non-existent --path: exit 2, one ERROR line, no traceback
# ---------------------------------------------------------------------------


def check_5_nonexistent_path() -> None:
    name = "5_nonexistent_path_exit2_one_error"
    try:
        result = _run("--path", "/nonexistent/path/xyz_manual_check")
        if result.returncode != 2:
            _fail(name, f"exit code {result.returncode}, expected 2")
            return
        error_lines = [
            l
            for l in result.stderr.splitlines()
            if l.strip() and not l.startswith("NOTICE")
        ]
        if len(error_lines) != 1:
            _fail(
                name,
                f"expected 1 error line (excluding NOTICE), got {len(error_lines)}:"
                f"\n{result.stderr}",
            )
            return
        if not error_lines[0].startswith("ERROR:"):
            _fail(name, f"error line does not start with 'ERROR:': {error_lines[0]!r}")
            return
        if "Traceback" in result.stderr or "Traceback" in result.stdout:
            _fail(name, "traceback found in output")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 6 — --path is a file: exit 2, one ERROR line
# ---------------------------------------------------------------------------


def check_6_path_is_file() -> None:
    name = "6_path_is_file_exit2_one_error"
    try:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fpath = f.name
        try:
            result = _run("--path", fpath)
            if result.returncode != 2:
                _fail(name, f"exit code {result.returncode}, expected 2")
                return
            error_lines = [
                l
                for l in result.stderr.splitlines()
                if l.strip() and not l.startswith("NOTICE")
            ]
            if len(error_lines) != 1:
                _fail(
                    name,
                    f"expected 1 error line, got {len(error_lines)}:\n{result.stderr}",
                )
                return
            if not error_lines[0].startswith("ERROR:"):
                _fail(
                    name,
                    f"error line does not start with 'ERROR:': {error_lines[0]!r}",
                )
                return
            _pass(name)
        finally:
            Path(fpath).unlink(missing_ok=True)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 7 — unknown flag: exit 2, error on stderr, no traceback, stdout empty
# ---------------------------------------------------------------------------


def check_7_unknown_flag() -> None:
    name = "7_unknown_flag_exit2_no_traceback"
    try:
        result = _run("--no-such-flag-xyz")
        if result.returncode != 2:
            _fail(name, f"exit code {result.returncode}, expected 2")
            return
        if not result.stderr.strip():
            _fail(name, "stderr is empty for unknown flag")
            return
        if "Traceback" in result.stderr or "Traceback" in result.stdout:
            _fail(name, "traceback found in output")
            return
        if result.stdout != "":
            _fail(name, f"stdout is not empty: {result.stdout!r}")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 8 — valid --timeout-* formats accepted (no exit 2)
# ---------------------------------------------------------------------------


def check_8_valid_timeout_formats() -> None:
    name = "8_valid_timeout_formats_accepted"
    formats = ["600", "90s", "30m", "1h", "1h30m"]
    try:
        for fmt in formats:
            result = _run_with_tmp("--timeout-build", fmt)
            if result.returncode == 2:
                _fail(
                    name,
                    f"valid timeout {fmt!r} rejected (exit 2):\n{result.stderr}",
                )
                return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 9 — bad --timeout-* value: exit 2, one ERROR line, no traceback
# ---------------------------------------------------------------------------


def check_9_bad_timeout_value() -> None:
    name = "9_bad_timeout_exit2_one_error"
    try:
        result = _run_with_tmp("--timeout-build", "notatime")
        if result.returncode != 2:
            _fail(name, f"exit code {result.returncode}, expected 2")
            return
        error_lines = [
            l
            for l in result.stderr.splitlines()
            if l.strip() and not l.startswith("NOTICE")
        ]
        if len(error_lines) != 1:
            _fail(
                name,
                f"expected 1 error line, got {len(error_lines)}:\n{result.stderr}",
            )
            return
        if not error_lines[0].startswith("ERROR:"):
            _fail(name, f"error line does not start with 'ERROR:': {error_lines[0]!r}")
            return
        if "Traceback" in result.stderr or "Traceback" in result.stdout:
            _fail(name, "traceback found in output")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 10 — all SPEC §11 flags parse without traceback
# ---------------------------------------------------------------------------


def check_10_all_spec_flags_parse() -> None:
    name = "10_all_spec_flags_parse_no_traceback"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
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
        if "Traceback" in result.stderr or "Traceback" in result.stdout:
            _fail(name, "traceback found in output")
            return
        if result.returncode not in (0, 3):
            _fail(
                name,
                f"unexpected exit code {result.returncode}; stderr:\n{result.stderr}",
            )
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 11 — nothing on stdout for error / empty-folder runs
# ---------------------------------------------------------------------------


def check_11_nothing_on_stdout_for_errors() -> None:
    name = "11_nothing_on_stdout_for_errors_or_empty_run"
    cases = [
        ("nonexistent path", ["--path", "/nonexistent/xyz_manual"]),
        ("unknown flag", ["--no-such-flag-xyz"]),
    ]
    try:
        for label, extra_args in cases:
            result = _run(*extra_args)
            if result.stdout != "":
                _fail(name, f"{label}: stdout is not empty: {result.stdout!r}")
                return
        # Empty folder dry-run also should produce no stdout
        result = _run_with_tmp("--dry-run")
        if result.stdout != "":
            _fail(name, f"empty folder dry-run: stdout is not empty: {result.stdout!r}")
            return
        _pass(name)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Check 12 — unreadable directory (Unix only)
# ---------------------------------------------------------------------------


def check_12_unreadable_path() -> None:
    name = "12_unreadable_path_exit2_one_error"
    if sys.platform == "win32":
        print(f"SKIP {name}: chmod not reliable on Windows")
        return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            locked = Path(tmp) / "locked"
            locked.mkdir()
            locked.chmod(0o000)
            try:
                result = _run("--path", str(locked))
                if result.returncode != 2:
                    _fail(name, f"exit code {result.returncode}, expected 2")
                    return
                error_lines = [
                    l
                    for l in result.stderr.splitlines()
                    if l.strip() and not l.startswith("NOTICE")
                ]
                if len(error_lines) != 1:
                    _fail(
                        name,
                        f"expected 1 error line, got {len(error_lines)}:\n{result.stderr}",
                    )
                    return
                if not error_lines[0].startswith("ERROR:"):
                    _fail(
                        name,
                        f"error line does not start with 'ERROR:': {error_lines[0]!r}",
                    )
                    return
                _pass(name)
            finally:
                locked.chmod(0o755)
    except Exception as exc:
        _fail(name, f"unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_CHECKS = [
    check_1_trust_notice_on_stderr,
    check_2_trust_notice_is_first_stderr_line,
    check_3_trust_notice_contains_resolved_path,
    check_4_trust_notice_mentions_trust,
    check_5_nonexistent_path,
    check_6_path_is_file,
    check_7_unknown_flag,
    check_8_valid_timeout_formats,
    check_9_bad_timeout_value,
    check_10_all_spec_flags_parse,
    check_11_nothing_on_stdout_for_errors,
    check_12_unreadable_path,
]

if __name__ == "__main__":
    for check in _CHECKS:
        try:
            check()
        except Exception as exc:
            name = check.__name__.split("check_", 1)[-1]
            _fail(name, f"unexpected exception: {exc}")
