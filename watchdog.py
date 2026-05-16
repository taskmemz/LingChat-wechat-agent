#!/usr/bin/env python3
"""
Watchdog: runs a command with a timeout, auto-kills on timeout.

Usage:
    python watchdog.py "python main.py" --timeout 30 --kill-all
    python watchdog.py --timeout 60 (default: "python main.py")
"""

import subprocess
import sys
import signal
import time
import os
import platform

DEFAULT_TIMEOUT = 60  # seconds


def kill_process(proc, kill_all=False):
    """Kill the process (and optionally all python processes)."""
    if kill_all:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "python3.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "python"], capture_output=True)
            subprocess.run(["pkill", "-9", "python3"], capture_output=True)
        print("[watchdog] Killed ALL python processes")
        return

    # Graceful first, then force
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)
        time.sleep(1)
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"[watchdog] Killed PID {proc.pid}")


def main():
    args = sys.argv[1:]
    cmd = "python main.py"
    timeout = DEFAULT_TIMEOUT
    kill_all = False

    i = 0
    while i < len(args):
        if args[i] == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1])
            i += 2
        elif args[i] == "--kill-all":
            kill_all = True
            i += 1
        else:
            cmd = " ".join(args)
            break

    start = time.time()
    print(f"[watchdog] RUNNING: {cmd}")
    print(f"[watchdog] timeout={timeout}s  kill_all={kill_all}")

    proc = subprocess.Popen(cmd, shell=True)

    while True:
        elapsed = time.time() - start
        if timeout > 0 and elapsed >= timeout:
            print(f"[watchdog] TIMEOUT after {int(elapsed)}s")
            kill_process(proc, kill_all=kill_all)
            sys.exit(1)

        ret = proc.poll()
        if ret is not None:
            print(f"[watchdog] EXITED with code {ret} in {int(elapsed)}s")
            sys.exit(ret)

        time.sleep(0.5)


if __name__ == "__main__":
    main()
