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


def kill_process(proc, kill_all=False, self_pid=None):
    """Kill the process (and optionally all python processes)."""
    if kill_all:
        killed = 0
        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/FI", "IMAGENAME eq python.exe"],
                capture_output=True, text=True
            )
            for line in result.stdout.split("\n")[1:]:
                if '"python.exe"' not in line:
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    pid_str = parts[1].strip('"')
                    try:
                        pid = int(pid_str)
                        if pid == self_pid:
                            continue
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                        killed += 1
                    except ValueError:
                        pass
        else:
            import signal
            try:
                result = subprocess.run(["pgrep", "-f", "python"], capture_output=True, text=True)
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    pid = int(line.strip())
                    if pid == self_pid:
                        continue
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        print(f"[watchdog] Killed {killed} other python processes")
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

    # 先提取 --timeout / --kill-all 参数，剩余的全拼接为命令
    cmd_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1])
            i += 2
        elif args[i] == "--kill-all":
            kill_all = True
            i += 1
        else:
            cmd_parts.append(args[i])
            i += 1
    if cmd_parts:
        cmd = " ".join(cmd_parts)

    start = time.time()
    print(f"[watchdog] RUNNING: {cmd}")
    print(f"[watchdog] timeout={timeout}s  kill_all={kill_all}")

    proc = subprocess.Popen(cmd, shell=True)

    while True:
        elapsed = time.time() - start
        if timeout > 0 and elapsed >= timeout:
            print(f"[watchdog] TIMEOUT after {int(elapsed)}s")
            kill_process(proc, kill_all=kill_all, self_pid=os.getpid())
            sys.exit(1)

        ret = proc.poll()
        if ret is not None:
            print(f"[watchdog] EXITED with code {ret} in {int(elapsed)}s")
            sys.exit(ret)

        time.sleep(0.5)


if __name__ == "__main__":
    main()
