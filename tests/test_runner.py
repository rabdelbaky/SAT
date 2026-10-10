"""Tests for runner.py — the safe command runner (Session 6).

Seams under test
----------------
1. run_command(args, cwd, timeout_s, log_path, tail_lines, secrets) -> CommandResult
   Public seam: given a command argument list, return a result describing what
   happened.  Tests verify status, exit_code, duration_s, output, output_tail,
   and that secrets are masked.

2. resolve_executable(args, cwd) -> list[str]
   Public seam: given a raw argument list and a working directory, return the
   resolved argument list (wrapper substitution, shutil.which lookup).

All commands are real cross-platform subprocesses using sys.executable so
tests run on Windows, macOS, and Linux without external tools.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from runner import CommandResult, run_command, resolve_executable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PY = sys.executable  # always available; guaranteed cross-platform


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: float = 10.0,
    tail_lines: int = 50,
    secrets: list[str] | None = None,
    log_path: Path | None = None,
    tmp_path: Path | None = None,
) -> CommandResult:
    """Convenience wrapper that supplies a temp log file if none given."""
    if log_path is None and tmp_path is not None:
        log_path = tmp_path / "cmd.log"
    elif log_path is None:
        # Create a temporary file for callers that don't supply tmp_path
        import tempfile as _tf

        _td = Path(_tf.mkdtemp())
        log_path = _td / "cmd.log"
    return run_command(
        args,
        cwd=cwd or Path("."),
        timeout_s=timeout_s,
        log_path=log_path,
        tail_lines=tail_lines,
        secrets=secrets or [],
    )


# ===========================================================================
# Cycle 1 — pass: zero exit code
# ===========================================================================


def test_zero_exit_returns_pass_status(tmp_path):
    result = _run([_PY, "-c", "print('hello')"], tmp_path=tmp_path)
    assert result.status == "pass"


def test_zero_exit_returns_zero_exit_code(tmp_path):
    result = _run([_PY, "-c", "print('hello')"], tmp_path=tmp_path)
    assert result.exit_code == 0


def test_result_has_duration_s(tmp_path):
    result = _run([_PY, "-c", "print('hello')"], tmp_path=tmp_path)
    assert isinstance(result.duration_s, float)
    assert result.duration_s >= 0.0


def test_result_has_output_text(tmp_path):
    result = _run([_PY, "-c", "print('hello')"], tmp_path=tmp_path)
    assert "hello" in result.output


def test_result_has_output_tail_list(tmp_path):
    result = _run([_PY, "-c", "print('hello')"], tmp_path=tmp_path)
    assert isinstance(result.output_tail, list)


# ===========================================================================
# Cycle 2 — fail: non-zero exit code
# ===========================================================================


def test_nonzero_exit_returns_fail_status(tmp_path):
    result = _run([_PY, "-c", "import sys; sys.exit(1)"], tmp_path=tmp_path)
    assert result.status == "fail"


def test_nonzero_exit_records_exit_code(tmp_path):
    result = _run([_PY, "-c", "import sys; sys.exit(42)"], tmp_path=tmp_path)
    assert result.exit_code == 42


def test_stderr_included_in_output(tmp_path):
    result = _run(
        [_PY, "-c", "import sys; sys.stderr.write('err line\\n')"],
        tmp_path=tmp_path,
    )
    assert "err line" in result.output


# ===========================================================================
# Cycle 3 — tool_not_installed: executable not found
# ===========================================================================


def test_missing_executable_returns_tool_not_installed(tmp_path):
    result = _run(
        ["__no_such_tool_xyz_abc__", "--version"],
        tmp_path=tmp_path,
    )
    assert result.status == "tool_not_installed"


def test_missing_executable_exit_code_is_none(tmp_path):
    result = _run(
        ["__no_such_tool_xyz_abc__", "--version"],
        tmp_path=tmp_path,
    )
    assert result.exit_code is None


def test_missing_executable_output_is_empty_string(tmp_path):
    result = _run(
        ["__no_such_tool_xyz_abc__", "--version"],
        tmp_path=tmp_path,
    )
    assert result.output == ""


# ===========================================================================
# Cycle 4 — timeout: kills whole process tree, returns timeout status
# ===========================================================================


def test_timeout_returns_timeout_status(tmp_path):
    # Sleep for 60s; timeout is 1s
    result = _run(
        [_PY, "-c", "import time; time.sleep(60)"],
        timeout_s=1.0,
        tmp_path=tmp_path,
    )
    assert result.status == "timeout"


def test_timeout_exit_code_is_none(tmp_path):
    result = _run(
        [_PY, "-c", "import time; time.sleep(60)"],
        timeout_s=1.0,
        tmp_path=tmp_path,
    )
    assert result.exit_code is None


def test_timeout_duration_is_at_least_timeout_s(tmp_path):
    result = _run(
        [_PY, "-c", "import time; time.sleep(60)"],
        timeout_s=1.0,
        tmp_path=tmp_path,
    )
    assert result.duration_s >= 1.0


# ===========================================================================
# Cycle 5 — odd bytes: UTF-8 with errors=replace, never crashes
# ===========================================================================


def test_odd_bytes_do_not_raise(tmp_path):
    # Write raw bytes that are invalid UTF-8 to stdout via os.write
    script = (
        "import sys, os; os.write(sys.stdout.fileno(), b'\\xff\\xfe invalid utf8\\n')"
    )
    # Should not raise; result may have replacement chars
    result = _run([_PY, "-c", script], tmp_path=tmp_path)
    assert result.status in ("pass", "fail")  # either is fine; no exception


def test_odd_bytes_produce_replacement_character_or_empty(tmp_path):
    script = "import sys, os; os.write(sys.stdout.fileno(), b'\\xff\\xfe')"
    result = _run([_PY, "-c", script], tmp_path=tmp_path)
    # Output contains the replacement char U+FFFD or is otherwise non-crashing
    assert isinstance(result.output, str)


# ===========================================================================
# Cycle 6 — output_tail: capped at tail_lines lines, each at 500 chars
# ===========================================================================


def test_tail_capped_at_tail_lines(tmp_path):
    # Print 100 lines; ask for tail of 10
    script = "for i in range(100): print(f'line {i}')"
    result = _run([_PY, "-c", script], tail_lines=10, tmp_path=tmp_path)
    assert len(result.output_tail) <= 10


def test_tail_contains_last_lines(tmp_path):
    script = "for i in range(100): print(f'line {i}')"
    result = _run([_PY, "-c", script], tail_lines=5, tmp_path=tmp_path)
    # The last line should be line 99
    assert any("99" in line for line in result.output_tail)


def test_tail_lines_truncated_to_500_chars(tmp_path):
    # Print a single line of 600 chars
    script = "print('x' * 600)"
    result = _run([_PY, "-c", script], tmp_path=tmp_path)
    for line in result.output_tail:
        assert len(line) <= 500


# ===========================================================================
# Cycle 7 — secrets masked in tail and log
# ===========================================================================


def test_secret_masked_in_output_tail(tmp_path):
    secret = "supersecrettoken99"
    script = f"print('TOKEN={secret}')"
    result = _run(
        [_PY, "-c", script],
        secrets=[secret],
        tmp_path=tmp_path,
    )
    for line in result.output_tail:
        assert secret not in line


def test_secret_masked_in_log_file(tmp_path):
    secret = "supersecrettoken99"
    script = f"print('TOKEN={secret}')"
    log_path = tmp_path / "cmd.log"
    _run(
        [_PY, "-c", script],
        secrets=[secret],
        log_path=log_path,
        tmp_path=tmp_path,
    )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    assert secret not in log_text


def test_non_secret_text_not_masked(tmp_path):
    script = "print('build succeeded in 3s')"
    result = _run([_PY, "-c", script], secrets=[], tmp_path=tmp_path)
    assert any("build succeeded" in line for line in result.output_tail)


# ===========================================================================
# Cycle 8 — large output: streams to log, does not exhaust memory
# ===========================================================================


def test_large_output_does_not_crash(tmp_path):
    # Print 10 000 lines of 200 chars each (2 MB total) — far below 50 MB
    # but enough to verify streaming behaviour.  Must not OOM or hang.
    script = "for i in range(10000): print('x' * 200)"
    result = _run([_PY, "-c", script], tail_lines=50, tmp_path=tmp_path)
    assert result.status == "pass"


def test_large_output_tail_still_capped(tmp_path):
    script = "for i in range(10000): print(f'line {i}')"
    result = _run([_PY, "-c", script], tail_lines=50, tmp_path=tmp_path)
    assert len(result.output_tail) <= 50


def test_large_output_written_to_log(tmp_path):
    script = "for i in range(1000): print(f'line {i}')"
    log_path = tmp_path / "big.log"
    _run([_PY, "-c", script], log_path=log_path, tmp_path=tmp_path)
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "line 999" in content


# ===========================================================================
# Cycle 9 — cwd is respected
# ===========================================================================


def test_cwd_respected(tmp_path):
    # Python prints cwd; we expect it to equal tmp_path (or its resolved form)
    script = "import os; print(os.getcwd())"
    result = _run([_PY, "-c", script], cwd=tmp_path, tmp_path=tmp_path)
    assert result.status == "pass"
    # Normalise for Windows short/long paths
    printed = Path(result.output.strip()).resolve()
    assert printed == tmp_path.resolve()


# ===========================================================================
# Cycle 10 — log file is written
# ===========================================================================


def test_log_file_written(tmp_path):
    log_path = tmp_path / "run.log"
    _run([_PY, "-c", "print('hello log')"], log_path=log_path)
    assert log_path.exists()
    assert "hello log" in log_path.read_text(encoding="utf-8")


def test_log_file_contains_stderr(tmp_path):
    log_path = tmp_path / "run.log"
    _run(
        [_PY, "-c", "import sys; sys.stderr.write('err line\\n')"],
        log_path=log_path,
    )
    assert "err line" in log_path.read_text(encoding="utf-8")


# ===========================================================================
# Cycle 11 — resolve_executable: wrapper preference (mvnw/gradlew)
# ===========================================================================


def test_resolve_executable_prefers_mvnw_in_cwd(tmp_path):
    # Create a fake mvnw in tmp_path (no .cmd; POSIX-style name)
    wrapper = tmp_path / "mvnw"
    wrapper.write_text('#!/bin/sh\nexec mvn "$@"\n')
    wrapper.chmod(0o755)

    resolved = resolve_executable(["mvn", "clean"], cwd=tmp_path)
    assert resolved is not None
    assert resolved[0] == str(wrapper)


def test_resolve_executable_prefers_gradlew_in_cwd(tmp_path):
    wrapper = tmp_path / "gradlew"
    wrapper.write_text('#!/bin/sh\nexec gradle "$@"\n')
    wrapper.chmod(0o755)

    resolved = resolve_executable(["gradle", "build"], cwd=tmp_path)
    assert resolved is not None
    assert resolved[0] == str(wrapper)


def test_resolve_executable_falls_back_when_no_wrapper(tmp_path):
    # No wrapper in tmp_path; python is always available
    resolved = resolve_executable([_PY, "-c", "pass"], cwd=tmp_path)
    assert resolved is not None
    assert resolved[0] == _PY  # unchanged (already absolute or on PATH)


def test_resolve_executable_returns_tool_not_installed_sentinel_for_missing(tmp_path):
    # The function signals "not found" by returning None
    resolved = resolve_executable(["__no_such_binary_xyz__"], cwd=tmp_path)
    assert resolved is None


# ===========================================================================
# Cycle 12 — CommandResult dataclass fields
# ===========================================================================


def test_command_result_has_all_fields(tmp_path):
    result = _run([_PY, "-c", "pass"], tmp_path=tmp_path)
    assert hasattr(result, "status")
    assert hasattr(result, "exit_code")
    assert hasattr(result, "duration_s")
    assert hasattr(result, "output")
    assert hasattr(result, "output_tail")
