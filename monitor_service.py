"""monitor_service.py — 独立窗口监听模式
每个发新消息的联系人开独立窗口，轮询可见文本检测新消息。
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

_IDLE_TIMEOUT = 30 * 60
_SCAN_INTERVAL = 5

_LOCK_TIMEOUT = 8


def _lock() -> bool:
    return wechat_lock.acquire(timeout=_LOCK_TIMEOUT)


def _unlock():
    try:
        wechat_lock.release()
    except RuntimeError:
        pass


class MonitorService:
    def __init__(self, config: AgentConfig, hub: HubClient):
        self.config = config
        self.hub = hub
        self._running = False
        self._main_window: Any = None
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
        entry = self._active.get(contact)
        return entry["window"] if entry else None

    async def reset_snapshot(self, contact: str):
        if contact not in self._active:
            return
        entry = self._active[contact]
        snapshot = await asyncio.get_event_loop().run_in_executor(
            None, self._read_visible, entry["window"]
        )
        if contact in self._active:
            self._active[contact]["_snapshot"] = snapshot

    # ── 扫描 ──

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

    # ── 独立窗口 ──

    async def _ensure_listener(self, contact: str):
        if contact in self._active:
            return

        logger.info(f"[LISTENER] opening window for '{contact}'")
        try:
            dialog = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._open_separate, contact
                ),
                timeout=15,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[LISTENER] open_separate TIMEOUT, fallback to main window read")
            await self._fallback_read_once(contact)
            return
        if dialog is None:
            logger.warning(f"[LISTENER] open_separate returned None, fallback to main window read")
            await self._fallback_read_once(contact)
            return

        logger.info(f"[LISTENER] window opened OK for '{contact}'")
        await asyncio.sleep(2)

        content = await asyncio.get_event_loop().run_in_executor(
            None, self._read_visible, dialog
        )
        logger.info(f"[LISTENER] first read for '{contact}': {len(content or '')}chars")
        if content:
            now = time.time()
            self._active[contact] = {
                "window": dialog, "task": None,
                "last_msg": now, "_snapshot": content,
            }
            await self._send_user_msg(contact, content)

        task = asyncio.create_task(self._listen_task(contact, dialog))
        self._active[contact] = {
            "window": dialog, "task": task, "last_msg": time.time(),
        }

    def _open_separate(self, contact: str):
        from pyweixin.WeChatTools import Navigator
        try:
            return Navigator.open_seperate_dialog_window(
                friend=contact, close_weixin=False
            )
        except Exception as e:
            logger.error(f"open_separate '{contact}': {e}")
            return None

    def _read_visible(self, dialog) -> str:
        """读取独立窗口里可见的消息文本（过滤窗口控件标签）"""
        # 微信窗口的固定控件文本，不是聊天消息
        _CHROME = {"置顶", "最小化", "最大化", "关闭", "×", "消息", ""}
        try:
            texts = []
            for ctrl in dialog.descendants():
                try:
                    t = ctrl.window_text().strip()
                except Exception:
                    continue
                if t not in _CHROME and len(t) > 1:
                    texts.append(t)
            return "\n".join(texts[-8:]) if texts else ""
        except Exception as e:
            logger.warning(f"read_visible error: {e}")
            return ""
            texts = []
            for cb in chat_list.children(control_type="CheckBox"):
                try:
                    t = cb.window_text().strip()
                except Exception:
                    continue
                if t and len(t) > 1:
                    texts.append(t)
            return "\n".join(texts[-8:]) if texts else ""
        except Exception as e:
            logger.warning(f"read_visible error: {e}")
            return ""

    async def _listen_task(self, contact: str, dialog):
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
        old_lines = old.split("\n")
        new_lines = new.split("\n")
        if len(new_lines) <= len(old_lines):
            return ""
        return "\n".join(new_lines[-(len(new_lines) - len(old_lines)):])

    # ── 回退（主窗口读一次）──

    async def _fallback_read_once(self, contact: str):
        from pyweixin.Uielements import Lists, SideBar, Main_window

        def read():
            if not _lock():
                return ""
            try:
                btn = self._main_window.child_window(**SideBar.Weixin)
                if btn.exists(timeout=0.5):
                    btn.click_input()
                sl = self._main_window.child_window(**Main_window.SessionList)
                if not sl.exists(timeout=1):
                    return ""
                for item in sl.children(control_type="ListItem"):
                    try:
                        aid = item.automation_id().replace("session_item_", "")
                        if aid == contact:
                            item.click_input()
                            break
                    except Exception:
                        continue
                import time as _t
                _t.sleep(1)
                area = self._main_window.child_window(**Lists.FriendChatList)
                if not area.exists(timeout=2):
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
                logger.error(f"fallback read error: {e}")
                return ""
            finally:
                _unlock()

        content = await asyncio.get_event_loop().run_in_executor(None, read)
        if content:
            logger.info(f"[FALLBACK] read {len(content)}chars for '{contact}'")
            await self._send_user_msg(contact, content)

    # ── 清理 ──

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(60)
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

    # ── 发送 ──

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
