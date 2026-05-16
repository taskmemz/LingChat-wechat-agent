#!/usr/bin/env python3
"""
常驻看门狗守护进程
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
监控所有 python.exe / python3 进程，
超过 TIMEOUT 秒就自动杀掉（不会杀自己）。

使用:
  # 启动守护（后台运行）
  python watchdog_daemon.py --timeout 120

  # 启动守护，指定排除进程名（含 watchdog 的不杀）
  python watchdog_daemon.py --timeout 300 --exclude vscode

  Ctrl+C 停止
"""

import sys
import os
import time
import platform
import subprocess
import signal
import argparse
from dataclasses import dataclass, field
from typing import Set

POLL_INTERVAL = 5  # 轮询间隔（秒）


@dataclass
class ProcInfo:
    pid: int
    create_time: float
    first_seen: float = field(default_factory=time.time)


class WatchdogDaemon:
    def __init__(self, timeout: int, exclude: list[str] | None = None):
        self.timeout = timeout
        self.exclude = exclude or []
        self._tracked: dict[int, ProcInfo] = {}
        self._self_pid = os.getpid()

    def run(self):
        print(f"[wd] 看门狗启动  timeout={self.timeout}s  exclude={self.exclude}")
        print(f"[wd] 自身 PID={self._self_pid}  轮询间隔={POLL_INTERVAL}s")
        print(f"[wd] 按 Ctrl+C 停止\n")

        try:
            while True:
                self._check()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n[wd] 停止")

    def _check(self):
        now = time.time()
        pids_now = self._list_python_pids()

        # 移除已不存在的进程
        dead = [pid for pid in self._tracked if pid not in pids_now]
        for pid in dead:
            del self._tracked[pid]

        # 记录新出现的进程
        for pid in pids_now:
            if pid not in self._tracked:
                self._tracked[pid] = ProcInfo(pid=pid, create_time=now)

        # 检查超时
        for pid, info in list(self._tracked.items()):
            elapsed = now - info.first_seen
            if elapsed >= self.timeout:
                self._kill_pid(pid, elapsed)
                del self._tracked[pid]

    def _list_python_pids(self) -> Set[int]:
        """返回当前所有 python 进程的 PID 集合（排除自己 + exclude 关键词）"""
        pids: Set[int] = set()

        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/FI", "IMAGENAME eq python.exe"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.split("\n")[1:]:
                    if '"python.exe"' not in line:
                        continue
                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1].strip('"'))
                            if pid != self._self_pid and not self._should_exclude(pid):
                                pids.add(pid)
                        except ValueError:
                            pass
            except Exception:
                pass
        else:
            try:
                result = subprocess.run(
                    ["pgrep", "-f", "python"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        pid = int(line.strip())
                        if pid != self._self_pid and not self._should_exclude(pid):
                            pids.add(pid)
                    except ValueError:
                        pass
            except Exception:
                pass

        return pids

    def _should_exclude(self, pid: int) -> bool:
        """检查进程命令行是否包含 exclude 关键词"""
        if not self.exclude:
            return False
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True, timeout=5,
                )
                # Windows tasklist 只给进程名，不给命令行
                # 简单处理：跳过 watchdog 自身的进程名匹配
                return False
            else:
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True, text=True, timeout=5,
                )
                cmd = result.stdout.strip().lower()
                for kw in self.exclude:
                    if kw in cmd:
                        return True
        except Exception:
            pass
        return False

    def _kill_pid(self, pid: int, elapsed: float):
        """强制终止进程"""
        print(f"[wd] KILL PID={pid}  (运行 {elapsed:.0f}s, 超时 {self.timeout}s)")
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception as e:
            print(f"[wd] 杀 {pid} 失败: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="常驻看门狗：监控所有 Python 进程，超时自动杀"
    )
    parser.add_argument(
        "--timeout", type=int, default=120,
        help="超时秒数（默认 120）",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[],
        help="排除关键词（命令行含这些关键词的进程不杀）",
    )
    args = parser.parse_args()

    daemon = WatchdogDaemon(timeout=args.timeout, exclude=args.exclude)
    daemon.run()


if __name__ == "__main__":
    main()
