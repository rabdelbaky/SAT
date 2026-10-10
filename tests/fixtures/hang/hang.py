"""Hang fixture: sleeps far longer than any reasonable timeout and spawns a
grandchild process that also sleeps.

Usage (cross-platform — uses sys.executable so no shell is needed):
    python hang.py [--print-pids]

With --print-pids, prints two lines to stdout:
    PARENT_PID=<pid>
    CHILD_PID=<pid>
so the caller can verify both processes are dead after the runner kills them.
"""

import os
import subprocess
import sys
import time

SLEEP_SECONDS = 3600  # 1 hour — far beyond any timeout used in tests


def main() -> None:
    print_pids = "--print-pids" in sys.argv

    # Spawn a grandchild that also sleeps for a long time.
    grandchild = subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({SLEEP_SECONDS})"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if print_pids:
        print(f"PARENT_PID={os.getpid()}", flush=True)
        print(f"CHILD_PID={grandchild.pid}", flush=True)

    # Sleep in the parent too.
    time.sleep(SLEEP_SECONDS)

    grandchild.wait()


if __name__ == "__main__":
    main()
