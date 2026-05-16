"""monitor_service.py — 独立窗口监听模式
每个发新消息的联系人开独立窗口，用 listen_on_chat 持续监听。
30 分钟无新消息自动关窗。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from config import AgentConfig
from hub_client import HubClient
from models import Envelope, MessageType
from wechat_lock import wechat_lock

logger = logging.getLogger("wechat-agent.monitor")

_IDLE_TIMEOUT = 30 * 60  # 30 分钟闲置自动关窗
_LISTEN_DURATION = "3s"   # 每次监听的时长
_SCAN_INTERVAL = 5        # 扫描会话列表的间隔（秒）


class MonitorService:
    def __init__(self, config: AgentConfig, hub: HubClient):
        self.config = config
        self.hub = hub
        self._running = False
        self._main_window: Any = None
        # {contact_name: {"window": WindowSpec, "task": asyncio.Task, "last_msg": float}}
        self._active: dict[str, dict] = {}

    async def start(self):
        self._running = True
        self._main_window = await asyncio.get_event_loop().run_in_executor(
            None, self._init_weixin
        )
        logger.info(f"WeChat window init: {self._main_window is not None}")
        asyncio.create_task(self._scan_loop())
        asyncio.create_task(self._cleanup_loop())
        logger.info("Monitor started")

    def _init_weixin(self):
        from pyweixin.WeChatTools import Navigator
        with wechat_lock:
            try:
                return Navigator.open_weixin(is_maximize=False)
            except Exception as e:
                logger.error(f"open_weixin failed: {e}")
                return None

    async def stop(self):
        self._running = False
        for name, info in list(self._active.items()):
            try:
                info["window"].close()
            except Exception:
                pass
            info["task"].cancel()
        self._active.clear()

    def get_window(self, contact: str):
        """返回活跃窗口引用，供 ToolExecutor 复用"""
        entry = self._active.get(contact)
        return entry["window"] if entry else None

    async def reset_snapshot(self, contact: str):
        """AI 回复发出后调用：刷新监听器的快照，避免把回复当新消息转发"""
        if contact not in self._active:
            return
        entry = self._active[contact]
        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(None, self._read_visible, entry["window"])
        if contact in self._active:
            self._active[contact]["_snapshot"] = snapshot

    # ============================================================
    # 扫描循环（轻量，只检测新联系人）
    # ============================================================

    async def _scan_loop(self):
        while self._running:
            try:
                if self._main_window is None:
                    await asyncio.sleep(_SCAN_INTERVAL)
                    continue
                new = await asyncio.get_event_loop().run_in_executor(
                    None, self._do_scan
                )
                for contact in new:
                    await self._ensure_listener(contact)
            except Exception as e:
                logger.error(f"Scan error: {e}")
            await asyncio.sleep(_SCAN_INTERVAL)

    def _do_scan(self) -> list[str]:
        """扫描会话列表，返回有新消息的联系人名称列表"""
        from pyweixin.utils import scan_for_new_messages
        with wechat_lock:
            try:
                result = scan_for_new_messages(
                    main_window=self._main_window, close_weixin=False
                )
                return list(result.keys())
            except Exception as e:
                logger.error(f"scan_for_new_messages: {e}")
                return []

    # ============================================================
    # 独立窗口 + 监听
    # ============================================================

    async def _ensure_listener(self, contact: str):
        """为联系人启动独立窗口监听（如尚未活跃）"""
        if contact in self._active:
            return

        logger.info(f"[LISTENER] opening window for '{contact}'")
        try:
            dialog = await asyncio.get_event_loop().run_in_executor(
                None, self._open_separate, contact
            )
            if dialog is None:
                return
        except Exception as e:
            logger.error(f"Failed to open separate dialog for '{contact}': {e}")
            return

        # 先读一次当前可见的消息（触发了扫描的那条）
        content = await asyncio.get_event_loop().run_in_executor(
            None, self._read_visible, dialog
        )
        if content:
            now = time.time()
            self._active[contact] = {"window": dialog, "task": None, "last_msg": now}
            await self._send_user_msg(contact, content)

        task = asyncio.create_task(self._listen_task(contact, dialog))
        self._active[contact] = {
            "window": dialog,
            "task": task,
            "last_msg": time.time(),
        }

    def _read_visible(self, dialog) -> str:
        """读取独立窗口里的可见消息文本"""
        import time as _t
        with wechat_lock:
            try:
                texts = []
                for ctrl in dialog.descendants():
                    try:
                        t = ctrl.window_text().strip()
                    except Exception:
                        continue
                    if t and len(t) > 1:
                        texts.append(t)
                return "\n".join(texts[-8:]) if texts else ""
            except Exception as e:
                logger.warning(f"read_visible error: {e}")
                return ""
                texts = []
                for ctrl in area.descendants():
                    try:
                        t = ctrl.window_text().strip()
                    except Exception:
                        continue
                    if t and len(t) > 1:
                        texts.append(t)
                return "\n".join(texts[-8:]) if texts else ""
            except Exception as e:
                logger.warning(f"read_visible '{contact}': {e}")
                return ""

    def _open_separate(self, contact: str):
        from pyweixin.WeChatTools import Navigator
        with wechat_lock:
            try:
                return Navigator.open_seperate_dialog_window(
                    friend=contact, close_weixin=False
                )
            except Exception as e:
                logger.error(f"open_seperate_dialog_window '{contact}': {e}")
                return None

    async def _listen_task(self, contact: str, dialog):
        """轮询独立窗口的可见文本，检测新消息"""
        # 初始化快照
        if contact in self._active:
            self._active[contact]["_snapshot"] = ""

        while self._running and contact in self._active:
            snapshot = await asyncio.get_event_loop().run_in_executor(
                None, self._read_visible, dialog
            )
            entry = self._active.get(contact)
            if not entry:
                break
            old = entry.get("_snapshot", "")
            if old and snapshot and snapshot != old:
                added = self._diff_content(old, snapshot)
                if added:
                    entry["last_msg"] = time.time()
                    entry["_snapshot"] = snapshot
                    await self._send_user_msg(contact, added)
            else:
                entry["_snapshot"] = snapshot or old
            await asyncio.sleep(3)

    def _diff_content(self, old: str, new: str) -> str:
        """对比新旧快照，返回新增的文本行"""
        old_lines = old.split("\n")
        new_lines = new.split("\n")
        # 新行数相同时无新消息
        if len(new_lines) <= len(old_lines):
            return ""
        # 返回多出来的行
        added = new_lines[- (len(new_lines) - len(old_lines)):]
        return "\n".join(added)

    # ============================================================
    # 清理过期窗口
    # ============================================================

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(60)  # 每分钟检查
            now = time.time()
            for contact, info in list(self._active.items()):
                if now - info["last_msg"] > _IDLE_TIMEOUT:
                    logger.info(f"[LISTENER] closing idle window for '{contact}'")
                    try:
                        info["window"].close()
                    except Exception:
                        pass
                    info["task"].cancel()
                    del self._active[contact]

    # ============================================================
    # 发送消息
    # ============================================================

    async def _send_user_msg(self, sender: str, content: str):
        logger.info(f"→ Hub: [{sender}] {content[:40]}...")
        await self.hub.send(
            Envelope(
                type=MessageType.USER_MESSAGE,
                from_node=self.hub.assigned_id or "",
                payload={
                    "session_id": sender,
                    "user_id": sender,
                    "content": content,
                    "message_type": "text",
                },
            )
        )
