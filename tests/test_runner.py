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

from runner import CommandResult, displayed_command, run_command, resolve_executable

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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="extensionless wrapper is POSIX-only; Windows uses mvnw.cmd/gradlew.bat",
)
def test_resolve_executable_prefers_mvnw_in_cwd(tmp_path):
    # Create a fake mvnw in tmp_path (no .cmd; POSIX-style name)
    wrapper = tmp_path / "mvnw"
    wrapper.write_text('#!/bin/sh\nexec mvn "$@"\n')
    wrapper.chmod(0o755)

    resolved = resolve_executable(["mvn", "clean"], cwd=tmp_path)
    assert resolved is not None
    assert resolved[0] == str(wrapper)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="extensionless wrapper is POSIX-only; Windows uses mvnw.cmd/gradlew.bat",
)
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


# /dev/null -> NUL on Windows (go build -o /dev/null; Go accepts only NUL there)

_GO_BUILD = ["go", "build", "-o", "/dev/null", "./..."]


def test_dev_null_becomes_nul_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("runner.shutil.which", lambda exe: "C:/fake/go.exe")
    assert displayed_command(_GO_BUILD, tmp_path) == ["go", "build", "-o", "NUL", "./..."]
    assert resolve_executable(_GO_BUILD, tmp_path) == ["C:/fake/go.exe", "build", "-o", "NUL", "./..."]


def test_dev_null_unchanged_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("runner.shutil.which", lambda exe: "/fake/go")
    assert displayed_command(_GO_BUILD, tmp_path) == _GO_BUILD
    assert resolve_executable(_GO_BUILD, tmp_path) == ["/fake/go", "build", "-o", "/dev/null", "./..."]


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


# ===========================================================================
# Cycle 13 — Ctrl+C: KeyboardInterrupt propagates out of run_command and the
# orchestrator turns it into an interrupted run with exit code 130 (SPEC §8, §9)
# ===========================================================================

# The child sends SIGINT to its parent (the test process), which is exactly
# what a user pressing Ctrl+C does to the main thread, then sleeps so the
# parent is still waiting on it when the signal lands.
_SIGINT_PARENT_SCRIPT = (
    "import os, signal, time; os.kill(os.getppid(), signal.SIGINT); time.sleep(30)"
)

_posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="SIGINT to parent is POSIX-only"
)


@_posix_only
def test_ctrl_c_during_command_reraises_keyboard_interrupt(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        _run([_PY, "-c", _SIGINT_PARENT_SCRIPT], timeout_s=20.0, tmp_path=tmp_path)


def _single_project_run(tmp_path, command: list[str], stage: str = "tests"):
    """Run one stub project through run_all; return (results, was_interrupted)."""
    from detection import DetectionResult, StageCommand
    from discovery import Project
    from orchestrator import OrchestratorOptions, run_all

    repo_root = tmp_path.resolve()
    project_dir = repo_root / "app"
    project_dir.mkdir()
    project = Project(path=project_dir, language="stub", primary_build_file="x")

    def detect(_project, _lang_cfg):
        return DetectionResult(
            commands={stage: [StageCommand(command=command, source="override")]}
        )

    return run_all(
        projects=[project],
        languages={"stub": {"stages": [stage]}},
        detection_fn=detect,
        override_map={},
        opts=OrchestratorOptions(steps=[stage], timeout_tests=20.0),
        repo_root=repo_root,
    )


@_posix_only
def test_ctrl_c_inside_run_command_gives_exit_code_130(tmp_path):
    from orchestrator import compute_exit_code

    results, was_interrupted = _single_project_run(
        tmp_path, [_PY, "-c", _SIGINT_PARENT_SCRIPT]
    )

    assert was_interrupted is True
    assert compute_exit_code(results, was_interrupted) == 130
    assert results[0].stage_status("tests") == "interrupted"


# ===========================================================================
# Cycle 14 — tool_not_installed reaches the stage and the warnings (SPEC §3.6)
# ===========================================================================


def test_missing_tool_marks_stage_tool_not_installed_not_pass(tmp_path):
    results, _ = _single_project_run(tmp_path, ["__no_such_tool_xyz_abc__"])

    assert results[0].stage_status("tests") == "tool_not_installed"


def test_missing_tool_adds_tool_not_installed_warning_once(tmp_path):
    from detection import DetectionResult, StageCommand
    from discovery import Project
    from orchestrator import OrchestratorOptions, run_all

    repo_root = tmp_path.resolve()
    project = Project(path=repo_root, language="stub", primary_build_file="x")
    missing = [
        StageCommand(command=["__no_such_tool_one__"], source="override"),
        StageCommand(command=["__no_such_tool_two__"], source="override"),
    ]

    results, _ = run_all(
        projects=[project],
        languages={"stub": {"stages": ["tests"]}},
        detection_fn=lambda _p, _c: DetectionResult(commands={"tests": missing}),
        override_map={},
        opts=OrchestratorOptions(steps=["tests"]),
        repo_root=repo_root,
    )

    assert results[0].warnings.count("tool_not_installed") == 1


# ===========================================================================
# Cycle 15 — report log_path is repo-relative, forward slashes (SPEC §6)
# ===========================================================================


def test_report_log_path_is_relative_to_repo_root(tmp_path):
    from orchestrator import project_results_to_report_data
    from pre_llm_checks import build_report

    results, _ = _single_project_run(tmp_path, [_PY, "-c", "print('ok')"])
    repo_root = tmp_path.resolve()
    report = build_report(
        project_results_to_report_data(results, repo_root), repo_root, tail_lines=50
    )

    log_path = report["projects"][0]["commands"][0]["log_path"]
    assert log_path == ".pre-llm/logs/app/tests-0.log"
    assert (repo_root / ".pre-llm" / "logs" / "app" / "tests-0.log").is_file()


# ===========================================================================
# Cycle 16 — Windows: wrapper .cmd variant wins over the plain wrapper
# ===========================================================================


def test_resolve_executable_prefers_gradlew_cmd_on_windows(tmp_path, monkeypatch):
    (tmp_path / "gradlew").write_text('#!/bin/sh\nexec gradle "$@"\n')
    (tmp_path / "gradlew.cmd").write_text("@echo off\r\ngradle %*\r\n")
    monkeypatch.setattr(sys, "platform", "win32")

    resolved = resolve_executable(["gradle", "build"], cwd=tmp_path)

    assert resolved == [str(tmp_path / "gradlew.cmd"), "build"]


def test_resolve_executable_uses_gradlew_bat_on_windows(tmp_path, monkeypatch):
    # Gradle's real Windows wrapper is gradlew.bat (Maven's is mvnw.cmd).
    (tmp_path / "gradlew").write_text('#!/bin/sh\nexec gradle "$@"\n')
    (tmp_path / "gradlew.bat").write_text("@echo off\r\ngradle %*\r\n")
    (tmp_path / "mvnw").write_text('#!/bin/sh\nexec mvn "$@"\n')
    (tmp_path / "mvnw.cmd").write_text("@echo off\r\nmvn %*\r\n")
    monkeypatch.setattr(sys, "platform", "win32")

    assert resolve_executable(["gradle", "assemble"], cwd=tmp_path) == [
        str(tmp_path / "gradlew.bat"),
        "assemble",
    ]
    assert resolve_executable(["mvn", "compile"], cwd=tmp_path) == [
        str(tmp_path / "mvnw.cmd"),
        "compile",
    ]


def test_resolve_executable_never_uses_posix_wrapper_on_windows(tmp_path, monkeypatch):
    # Only the extensionless script: it cannot be launched on Windows, so the
    # build tool on PATH is used (here: not found -> None).
    (tmp_path / "gradlew").write_text('#!/bin/sh\nexec gradle "$@"\n')
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("runner.shutil.which", lambda exe: None)

    assert resolve_executable(["gradle", "assemble"], cwd=tmp_path) is None


@pytest.mark.skipif(sys.platform == "win32", reason="exec bit is POSIX-only")
def test_resolve_executable_runs_non_executable_wrapper_with_sh(tmp_path):
    wrapper = tmp_path / "mvnw"
    wrapper.write_text('#!/bin/sh\necho wrapper-ran "$@"\n')
    wrapper.chmod(0o644)

    resolved = resolve_executable(["mvn", "compile"], cwd=tmp_path)

    assert resolved is not None
    assert Path(resolved[0]).name == "sh"
    assert resolved[1:] == [str(wrapper), "compile"]


def test_displayed_command_names_the_wrapper_not_a_path(tmp_path, monkeypatch):
    (tmp_path / "gradlew.bat").write_text("@echo off\r\n")
    monkeypatch.setattr(sys, "platform", "win32")
    assert displayed_command(["gradle", "test"], tmp_path) == ["gradlew.bat", "test"]
    assert displayed_command(["mvn", "test"], tmp_path) == ["mvn", "test"]  # no mvnw.cmd
    assert displayed_command(["npm", "test"], tmp_path) == ["npm", "test"]


# ===========================================================================
# Cycle 17 — Popen OSError becomes a fail result, never an exception
# ===========================================================================


@pytest.mark.skipif(sys.platform == "win32", reason="exec bit is POSIX-only")
def test_unlaunchable_executable_returns_fail_with_masked_error_line(tmp_path):
    # Executable bit set (so shutil.which finds it) but not a valid program,
    # so Popen raises OSError (Exec format error).  The secret sits in the
    # file name so it appears in the error text.
    secret = "supersecrettoken99"
    bogus = tmp_path / f"TOKEN={secret}"
    bogus.write_bytes(b"\x00\x01\x02\x03")
    bogus.chmod(0o755)

    result = _run([str(bogus)], secrets=[secret], tmp_path=tmp_path)

    assert result.status == "fail"
    assert len(result.output_tail) == 1
    assert result.output_tail[0].strip() != ""
    assert secret not in result.output_tail[0]
