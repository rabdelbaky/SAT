"""Safe command runner for Pre-LLM Checks (Session 6).

Public API
----------
resolve_executable(args, cwd) -> list[str] | None
    Resolve the first element of *args* to a real path:
      1. If the command is mvn/gradle, a wrapper in *cwd* wins: mvnw/gradlew
         on POSIX (run with sh if not executable), mvnw.cmd/gradlew.bat
         (or gradlew.cmd) on Windows.
      2. Use shutil.which to locate the executable on PATH.
      3. Return None if the executable cannot be found (caller maps to
         tool_not_installed).

displayed_command(args, cwd) -> list[str]
    *args* with mvn/gradle replaced by the wrapper's file name when a
    wrapper will run (for the report; never a path).

On Windows both functions replace an argument that is exactly ``/dev/null``
with ``NUL`` (e.g. ``go build -o /dev/null``); Go accepts only ``NUL`` there.

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

from masking import mask_secrets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_LINE_LEN: int = 500
# Build tool -> (POSIX wrapper script, Windows wrapper scripts in order).
# Gradle's Windows wrapper is gradlew.bat; Maven's is mvnw.cmd.
_WRAPPERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mvn": ("mvnw", ("mvnw.cmd",)),
    "gradle": ("gradlew", ("gradlew.bat", "gradlew.cmd")),
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


def _mask(text: str, secrets: list[str]) -> str:
    """Apply both pattern-based masking and literal secret replacement."""
    text = mask_secrets(text)
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


def _find_wrapper(exe: str, cwd: Path) -> list[str] | None:
    """Return the argv prefix for a mvnw/gradlew wrapper in *cwd*, or None.

    Windows: only the .cmd/.bat wrapper is used; the extensionless POSIX
    script cannot be launched there, so without a .cmd/.bat the build tool
    on PATH is used instead.  POSIX: a wrapper without the executable bit
    (common after a zip download) is run with ``sh``.
    """
    name = Path(exe).name.lower()
    for suffix in (".cmd", ".bat", ".exe"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    entry = _WRAPPERS.get(name)
    if entry is None:
        return None
    posix_name, windows_names = entry
    if sys.platform == "win32":
        for win_name in windows_names:
            path = cwd / win_name
            if path.is_file():
                return [str(path)]
        return None
    path = cwd / posix_name
    if not path.is_file():
        return None
    if os.access(path, os.X_OK):
        return [str(path)]
    sh = shutil.which("sh")
    return [sh, str(path)] if sh else None


def _null_device(args: list[str]) -> list[str]:
    """On Windows, each argument that is exactly ``/dev/null`` becomes ``NUL``."""
    if sys.platform != "win32":
        return args
    return ["NUL" if arg == "/dev/null" else arg for arg in args]


def displayed_command(args: list[str], cwd: Path) -> list[str]:
    """Return *args* as the report shows them: the wrapper's file name in
    place of mvn/gradle when :func:`_find_wrapper` would use one (e.g.
    ``["gradlew.bat", "assemble"]``), else *args* unchanged.  Never a path,
    so the report stays relative and the environment block never probes the
    PATH tool for a run the wrapper did.
    """
    if not args:
        return args
    args = _null_device(args)
    wrapper = _find_wrapper(args[0], cwd)
    if wrapper is None:
        return args
    return [Path(wrapper[-1]).name] + args[1:]


def resolve_executable(args: list[str], cwd: Path) -> list[str] | None:
    """Resolve the executable in *args* and return the updated argument list.

    Returns ``None`` if the executable cannot be found (caller should set
    status ``tool_not_installed``).

    Wrapper preference: if the command is ``mvn`` or ``gradle``, a wrapper
    in *cwd* wins (see :func:`_find_wrapper`).
    """
    if not args:
        return None

    args = _null_device(args)
    exe = args[0]
    wrapper = _find_wrapper(exe, cwd)
    if wrapper is not None:
        return wrapper + args[1:]

    # A relative path with a separator (vendor/bin/phpunit, ./bin/rails) is
    # relative to the PROJECT folder, not to this process's working directory.
    # On Windows the extensionless file is never used: Composer writes both
    # vendor/bin/phpunit (a PHP proxy Windows cannot launch) and phpunit.bat.
    if ("/" in exe or "\\" in exe) and not Path(exe).is_absolute():
        if sys.platform != "win32":
            suffixes: tuple[str, ...] = ("",)
        elif exe.lower().endswith((".bat", ".cmd", ".exe", ".com")):
            suffixes = ("",)
        else:
            suffixes = (".bat", ".cmd", ".exe")
        for suffix in suffixes:
            candidate = cwd / (exe + suffix)
            if candidate.is_file():
                return [str(candidate)] + args[1:]
        return None

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
