"""Manual runner checks for Session 6 (runner.py).

Run as:
    python tests/manual_runner_check.py

Prints one PASS/FAIL line per check.  All commands use sys.executable so
the script is cross-platform (Windows, macOS, Linux).

Special mode:
    python tests/manual_runner_check.py --interactive-hang

Starts a sleeping command so you can press Ctrl+C.  Prints "interrupted"
and confirms the child process is gone.

Exit code: 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# Ensure the repo root is on the path so runner can be imported
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from runner import CommandResult, run_command  # noqa: E402

_PY = sys.executable
_PASS = "PASS"
_FAIL = "FAIL"

_results: list[tuple[int, str, str]] = []  # (check_num, PASS/FAIL, description)


def _check(num: int, description: str, *, ok: bool, detail: str = "") -> None:
    label = _PASS if ok else _FAIL
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"{label}  {num:2d}. {description}{suffix}")
    _results.append((num, label, description))


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: float = 10.0,
    tail_lines: int = 50,
    secrets: list[str] | None = None,
    tmp_dir: Path,
) -> CommandResult:
    log_path = tmp_dir / f"check_{len(_results)}.log"
    return run_command(
        args,
        cwd=cwd or tmp_dir,
        timeout_s=timeout_s,
        log_path=log_path,
        tail_lines=tail_lines,
        secrets=secrets or [],
    )


# ---------------------------------------------------------------------------
# Interactive hang mode
# ---------------------------------------------------------------------------


def _interactive_hang() -> None:
    """Run a sleeping child and wait for Ctrl+C."""
    print("Running sleeping child (pid will be shown).  Press Ctrl+C to interrupt.")
    print("You should see: status=interrupted, child process gone.")
    print()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        log_path = tmp / "hang.log"

        # Use a script that prints its own PID so we can verify it's gone
        script = (
            "import os, time, sys; "
            "print(f'CHILD_PID={os.getpid()}', flush=True); "
            "time.sleep(3600)"
        )
        result = run_command(
            [_PY, "-c", script],
            cwd=tmp,
            timeout_s=3600.0,
            log_path=log_path,
            tail_lines=50,
            secrets=[],
        )

    print(f"\nstatus: {result.status}")
    if result.status == "interrupted":
        print("Correct: got 'interrupted'.")
        # Try to find the PID from the tail
        child_pid: int | None = None
        for line in result.output_tail:
            if line.startswith("CHILD_PID="):
                try:
                    child_pid = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
        if child_pid is not None:
            alive = _pid_alive(child_pid)
            if alive:
                print(f"WARNING: child PID {child_pid} is still alive!")
            else:
                print(f"Child PID {child_pid} is gone — correct.")
        else:
            print("(Could not extract child PID from output.)")
    else:
        print(f"WARNING: expected 'interrupted' but got {result.status!r}.")

    sys.exit(130)


# ---------------------------------------------------------------------------
# PID alive helper
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* is still alive."""
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle == 0:
            return False
        import ctypes.wintypes

        result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        ctypes.windll.kernel32.CloseHandle(handle)
        # WAIT_TIMEOUT (0x102) means still alive; WAIT_OBJECT_0 (0) means terminated
        return result == 0x102
    else:
        # Linux: a zombie (killed, not yet reaped by its parent) still answers
        # os.kill(pid, 0) but is dead.  /proc/<pid>/stat: "pid (comm) S ...".
        stat = Path(f"/proc/{pid}/stat")
        if sys.platform.startswith("linux") and stat.exists():
            try:
                state = stat.read_text().rsplit(")", 1)[1].split()[0]
            except (OSError, IndexError):
                state = ""
            if state == "Z":
                return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not ours


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def run_checks() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # ------------------------------------------------------------------
        # Check 1: pass — zero exit code
        # ------------------------------------------------------------------
        r = _run([_PY, "-c", "print('hello')"], tmp_dir=tmp)
        _check(
            1,
            "pass — zero exit returns status='pass'",
            ok=r.status == "pass",
            detail=f"got {r.status!r}",
        )

        # ------------------------------------------------------------------
        # Check 2: fail — non-zero exit code
        # ------------------------------------------------------------------
        r = _run([_PY, "-c", "import sys; sys.exit(3)"], tmp_dir=tmp)
        _check(
            2,
            "fail — exit 3 returns status='fail' with exit_code=3",
            ok=r.status == "fail" and r.exit_code == 3,
            detail=f"status={r.status!r} exit_code={r.exit_code}",
        )

        # ------------------------------------------------------------------
        # Check 3: tool_not_installed — unknown executable
        # ------------------------------------------------------------------
        r = _run(["__no_such_tool_xyz_abc_123__", "--version"], tmp_dir=tmp)
        _check(
            3,
            "tool_not_installed — missing exe returns status='tool_not_installed'",
            ok=r.status == "tool_not_installed",
            detail=f"got {r.status!r}",
        )

        # ------------------------------------------------------------------
        # Check 4: timeout in about 2 s
        # ------------------------------------------------------------------
        t0 = time.monotonic()
        r = _run(
            [_PY, "-c", "import time; time.sleep(60)"],
            timeout_s=2.0,
            tmp_dir=tmp,
        )
        elapsed = time.monotonic() - t0
        _check(
            4,
            "timeout — 2 s timeout returns status='timeout'",
            ok=r.status == "timeout" and elapsed < 10.0,
            detail=f"status={r.status!r} elapsed={elapsed:.1f}s",
        )

        # ------------------------------------------------------------------
        # Check 5: grandchild is dead after timeout
        # ------------------------------------------------------------------
        hang_script = Path(_REPO_ROOT) / "tests" / "fixtures" / "hang" / "hang.py"
        log5 = tmp / "hang5.log"
        r5 = run_command(
            [_PY, str(hang_script), "--print-pids"],
            cwd=tmp,
            timeout_s=2.0,
            log_path=log5,
            tail_lines=50,
            secrets=[],
        )
        # Parse child PID from output
        child_pid5: int | None = None
        for line in r5.output_tail:
            if line.startswith("CHILD_PID="):
                try:
                    child_pid5 = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
        if child_pid5 is None:
            # Fall back to log file (tail may have missed early output)
            try:
                log_text = log5.read_text(encoding="utf-8", errors="replace")
                for line in log_text.splitlines():
                    if line.startswith("CHILD_PID="):
                        try:
                            child_pid5 = int(line.split("=", 1)[1].strip())
                        except ValueError:
                            pass
            except FileNotFoundError:
                pass

        if child_pid5 is None:
            _check(
                5,
                "grandchild dead after timeout",
                ok=False,
                detail="could not parse CHILD_PID from output",
            )
        else:
            # Give the OS a moment to reap
            time.sleep(0.2)
            alive = _pid_alive(child_pid5)
            _check(
                5,
                f"grandchild (PID {child_pid5}) is dead after timeout",
                ok=not alive,
                detail="process still alive" if alive else "",
            )

        # ------------------------------------------------------------------
        # Check 6: odd bytes do not crash
        # ------------------------------------------------------------------
        script6 = (
            "import sys, os; os.write(sys.stdout.fileno(), b'\\xff\\xfe odd bytes\\n')"
        )
        try:
            r = _run([_PY, "-c", script6], tmp_dir=tmp)
            ok6 = isinstance(r.output, str)
        except Exception as exc:  # noqa: BLE001
            ok6 = False
        _check(
            6,
            "odd bytes — invalid UTF-8 does not crash",
            ok=ok6,
            detail="raised an exception",
        )

        # ------------------------------------------------------------------
        # Check 7: tail capped at 50 lines and 500 chars
        # ------------------------------------------------------------------
        script7 = "for i in range(100): print(f'line {i}: ' + 'x' * 600)"
        r = _run([_PY, "-c", script7], tail_lines=50, tmp_dir=tmp)
        lines_ok = len(r.output_tail) <= 50
        chars_ok = all(len(line) <= 500 for line in r.output_tail)
        _check(
            7,
            "tail capped at 50 lines, each ≤ 500 chars",
            ok=lines_ok and chars_ok,
            detail=f"lines={len(r.output_tail)} max_chars={max((len(l) for l in r.output_tail), default=0)}",
        )

        # ------------------------------------------------------------------
        # Check 8: secret in output is masked
        # ------------------------------------------------------------------
        secret = "VERY_SECRET_VALUE_12345"
        script8 = f"print('TOKEN={secret}')"
        r = _run([_PY, "-c", script8], secrets=[secret], tmp_dir=tmp)
        tail_masked = all(secret not in line for line in r.output_tail)
        log8 = tmp / f"check_{len(_results) - 1}.log"
        try:
            log_text8 = log8.read_text(encoding="utf-8", errors="replace")
            log_masked = secret not in log_text8
        except FileNotFoundError:
            log_masked = False
        _check(
            8,
            "secret in output is masked in tail and log",
            ok=tail_masked and log_masked,
            detail=f"tail_masked={tail_masked} log_masked={log_masked}",
        )

        # ------------------------------------------------------------------
        # Check 9: large output does not hang
        # ------------------------------------------------------------------
        # 10 000 lines × 200 chars = ~2 MB; should complete well within 30 s
        script9 = "for i in range(10000): print('x' * 200)"
        t0 = time.monotonic()
        r = _run([_PY, "-c", script9], tail_lines=50, timeout_s=30.0, tmp_dir=tmp)
        elapsed9 = time.monotonic() - t0
        _check(
            9,
            "large output (~2 MB) does not hang",
            ok=r.status == "pass" and elapsed9 < 30.0,
            detail=f"status={r.status!r} elapsed={elapsed9:.1f}s",
        )

        # ------------------------------------------------------------------
        # Check 10: cwd is respected
        # ------------------------------------------------------------------
        sub_dir = tmp / "workdir"
        sub_dir.mkdir()
        script10 = "import os; print(os.getcwd())"
        r = _run([_PY, "-c", script10], cwd=sub_dir, tmp_dir=tmp)
        if r.status == "pass" and r.output.strip():
            reported = Path(r.output.strip()).resolve()
            cwd_ok = reported == sub_dir.resolve()
        else:
            cwd_ok = False
        _check(
            10,
            "cwd is respected",
            ok=cwd_ok,
            detail=f"reported={r.output.strip()!r} expected={str(sub_dir)!r}",
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    passed = sum(1 for _, label, _ in _results if label == _PASS)
    total = len(_results)
    print(
        f"{'All checks passed' if passed == total else 'Some checks FAILED'}: {passed}/{total}"
    )

    return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    if "--interactive-hang" in sys.argv:
        _interactive_hang()
    else:
        sys.exit(run_checks())
