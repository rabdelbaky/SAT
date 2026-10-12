"""Safe command runner for Pre-LLM Checks (Session 6).

Public API
----------
resolve_executable(args, cwd) -> list[str] | None
    Resolve the first element of *args* to a real path:
      1. If the command is mvn/gradle (or mvn.cmd/gradle.cmd on Windows),
         look for mvnw/gradlew (or mvnw.cmd/gradlew.cmd) in *cwd* first.
      2. Use shutil.which to locate the executable on PATH.
      3. Return None if the executable cannot be found (caller maps to
         tool_not_installed).

run_command(args, cwd, timeout_s, log_path, tail_lines, secrets) -> CommandResult
    Run *args* as a subprocess with shell=False, stream combined
    stdout+stderr to *log_path*, and return a CommandResult.

    Status values (SPEC §5):
      pass              — exited 0
      fail              — exited non-zero
      timeout           — killed after timeout_s
      tool_not_installed — executable not found via shutil.which

    On KeyboardInterrupt (Ctrl+C) the tree is killed and the exception is
    re-raised; no result is returned.

    The whole process tree is killed on timeout or Ctrl+C so no orphan
    processes are left behind (POSIX: new session + killpg; Windows:
    taskkill /T /F).

    Output is decoded as UTF-8 with errors="replace" so odd bytes never
    crash the tool.  The full combined output is streamed to *log_path*
    (secrets masked).  Only the last *tail_lines* lines are kept in
    memory (each truncated to 500 chars, secrets masked) as output_tail.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_LINE_LEN: int = 500
_WRAPPER_MAP: dict[str, str] = {
    "mvn": "mvnw",
    "gradle": "gradlew",
    # .cmd variants (Windows)
    "mvn.cmd": "mvnw.cmd",
    "gradle.cmd": "gradlew.cmd",
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    """The outcome of a single command run."""

    status: str  # pass | fail | timeout | interrupted | tool_not_installed
    exit_code: Optional[int]  # None for timeout/interrupted/tool_not_installed
    duration_s: float
    output: str  # combined stdout+stderr (full, unmasked in memory)
    output_tail: list[str]  # last N lines, each ≤500 chars, secrets masked


# ---------------------------------------------------------------------------
# Secret masking
# ---------------------------------------------------------------------------


def _mask_literal_secrets(text: str, secrets: list[str]) -> str:
    """Replace every literal string in *secrets* with ``***`` in *text*."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


# Also import the pattern-based masker from pre_llm_checks so the runner
# applies the same masking rules as the report writer.
try:
    # Allow the module to be imported even when pre_llm_checks is not on sys.path
    _module_dir = Path(__file__).parent
    if str(_module_dir) not in sys.path:
        sys.path.insert(0, str(_module_dir))
    from pre_llm_checks import mask_secrets as _pattern_mask_secrets
except ImportError:  # pragma: no cover – standalone use

    def _pattern_mask_secrets(text: str) -> str:  # type: ignore[misc]
        return text


def _mask(text: str, secrets: list[str]) -> str:
    """Apply both pattern-based masking and literal secret replacement."""
    text = _pattern_mask_secrets(text)
    text = _mask_literal_secrets(text, secrets)
    return text


# ---------------------------------------------------------------------------
# Output tail helpers
# ---------------------------------------------------------------------------


def _build_tail(lines: list[str], tail_lines: int, secrets: list[str]) -> list[str]:
    """Return the last *tail_lines* lines, each masked and truncated to 500 chars."""
    tail = lines[-tail_lines:] if len(lines) > tail_lines else list(lines)
    result = []
    for line in tail:
        masked = _mask(line, secrets)
        result.append(masked[:_MAX_LINE_LEN])
    return result


# ---------------------------------------------------------------------------
# Process-tree kill helpers
# ---------------------------------------------------------------------------


def _kill_tree_windows(pid: int) -> None:
    """Kill *pid* and its entire child tree on Windows using taskkill."""
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass


def _kill_tree_posix(pid: int) -> None:
    """Kill the process group that contains *pid* on POSIX systems."""
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:  # noqa: BLE001
        pass


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        _kill_tree_windows(pid)
    else:
        _kill_tree_posix(pid)


# ---------------------------------------------------------------------------
# Executable resolution
# ---------------------------------------------------------------------------


def resolve_executable(args: list[str], cwd: Path) -> list[str] | None:
    """Resolve the executable in *args* and return the updated argument list.

    Returns ``None`` if the executable cannot be found (caller should set
    status ``tool_not_installed``).

    Wrapper preference: if the command is ``mvn`` or ``gradle`` (or their
    ``.cmd`` variants on Windows), look for ``mvnw`` / ``gradlew`` (or
    ``.cmd`` variants) in *cwd* first.
    """
    if not args:
        return None

    exe = args[0]
    exe_basename = Path(exe).name  # strip any path prefix for lookup

    # On Windows, also consider the .cmd variant when checking wrappers
    candidates: list[str] = [exe_basename]
    if sys.platform == "win32" and not exe_basename.lower().endswith(".cmd"):
        candidates.append(exe_basename + ".cmd")

    for candidate in candidates:
        candidate_lower = candidate.lower()
        wrapper_name = _WRAPPER_MAP.get(candidate_lower) or _WRAPPER_MAP.get(candidate)
        if wrapper_name:
            # On Windows the .cmd variant comes first (SPEC §3.6)
            if sys.platform == "win32" and not wrapper_name.endswith(".cmd"):
                wrapper_cmd = cwd / (wrapper_name + ".cmd")
                if wrapper_cmd.exists():
                    return [str(wrapper_cmd)] + args[1:]
            wrapper_path = cwd / wrapper_name
            if wrapper_path.exists():
                return [str(wrapper_path)] + args[1:]

    # No wrapper found; resolve via shutil.which
    resolved = shutil.which(exe)
    if resolved is None:
        return None
    return [resolved] + args[1:]


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def run_command(
    args: list[str],
    cwd: Path,
    timeout_s: float,
    log_path: Path,
    tail_lines: int = 50,
    secrets: list[str] | None = None,
) -> CommandResult:
    """Run *args* safely and return a :class:`CommandResult`.

    The command is run with ``shell=False``.  The executable is first
    resolved via :func:`resolve_executable`; if it is not found, a
    ``tool_not_installed`` result is returned immediately without raising.

    stdout and stderr are combined and streamed line-by-line to *log_path*
    (with secrets masked).  Only the last *tail_lines* lines are kept in
    memory.  Lines longer than 500 chars are truncated in the tail.

    On timeout the whole process tree is killed and ``status="timeout"``
    is returned.  On :exc:`KeyboardInterrupt` the whole process tree is
    killed, the log is closed, and the :exc:`KeyboardInterrupt` is re-raised
    so the caller can mark the run interrupted and still write a report.
    """
    if secrets is None:
        secrets = []

    start = time.monotonic()

    # --- Resolve executable -------------------------------------------------
    resolved_args = resolve_executable(args, cwd)
    if resolved_args is None:
        return CommandResult(
            status="tool_not_installed",
            exit_code=None,
            duration_s=0.0,
            output="",
            output_tail=[],
        )

    # --- Prepare process creation options -----------------------------------
    kwargs: dict = {
        "args": resolved_args,
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,  # merge stderr into stdout
        "shell": False,
    }
    if sys.platform != "win32":
        # Put the child in its own process group so we can kill the tree
        kwargs["start_new_session"] = True

    # --- Ensure log directory exists ----------------------------------------
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # --- State shared between the reader thread and the main thread ---------
    all_lines: list[str] = []  # full output, line by line (unmasked)

    def _reader(pipe, log_fh):
        """Read lines from *pipe*, write masked lines to *log_fh*, keep all lines."""
        for raw_line in pipe:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            all_lines.append(line)
            masked_line = _mask(line, secrets)
            log_fh.write(masked_line + "\n")
            log_fh.flush()

    # --- Launch process and reader thread -----------------------------------
    status: str = "pass"
    exit_code: Optional[int] = None
    reader_thread: threading.Thread | None = None
    proc: subprocess.Popen | None = None
    log_fh = None

    try:
        log_fh = open(log_path, "w", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(**kwargs)  # type: ignore[call-overload]
        except OSError as exc:
            # Found but could not be launched (bad format, permissions, ...):
            # a fail whose only output line is the error text.
            error_line = str(exc)
            log_fh.write(_mask(error_line, secrets) + "\n")
            return CommandResult(
                status="fail",
                exit_code=None,
                duration_s=time.monotonic() - start,
                output=error_line,
                output_tail=_build_tail([error_line], tail_lines, secrets),
            )

        reader_thread = threading.Thread(
            target=_reader,
            args=(proc.stdout, log_fh),
            daemon=True,
        )
        reader_thread.start()

        # Wait for the process to finish or timeout
        try:
            exit_code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
            proc.wait()  # reap the zombie
            status = "timeout"
            exit_code = None
        else:
            if exit_code != 0:
                status = "fail"

        # Wait for the reader to drain all remaining output
        reader_thread.join(timeout=5.0)

    except KeyboardInterrupt:
        # Ctrl+C: kill the process tree, drain remaining output, then re-raise
        # (the finally block closes the log first).  The orchestrator catches
        # it, marks the command interrupted, and the caller exits with 130.
        if proc is not None:
            _kill_tree(proc.pid)
            try:
                proc.wait(timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
        if reader_thread is not None:
            reader_thread.join(timeout=5.0)
        raise

    finally:
        if log_fh is not None:
            try:
                log_fh.close()
            except Exception:  # noqa: BLE001
                pass

    duration_s = time.monotonic() - start
    output = "\n".join(all_lines)
    output_tail = _build_tail(all_lines, tail_lines, secrets)

    return CommandResult(
        status=status,
        exit_code=exit_code,
        duration_s=duration_s,
        output=output,
        output_tail=output_tail,
    )
