from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from config import AgentConfig
from hub_client import HubClient
from models import Envelope, MessageType
from wechat_lock import wechat_lock

logger = logging.getLogger("wechat-agent.monitor")

_BACKOFF_SCHEDULE = [2, 5, 15, 30, 60]


class MonitorService:
    def __init__(self, config: AgentConfig, hub: HubClient):
        self.config = config
        self.hub = hub
        self._running = False
        self._consecutive_errors = 0
        self._main_window: Any = None

    async def start(self):
        self._running = True
        loop = asyncio.get_event_loop()
        self._main_window = await loop.run_in_executor(None, self._init_weixin)
        logger.info(f"WeChat window initialized: {self._main_window is not None}")
        asyncio.create_task(self._monitor_loop())
        logger.info("Monitor service started")

    def _init_weixin(self):
        with wechat_lock:
            from pyweixin.WeChatTools import Navigator
            try:
                return Navigator.open_weixin(is_maximize=False)
            except Exception as e:
                logger.error(f"Failed to open WeChat: {e}")
                return None

    async def stop(self):
        self._running = False

    async def _monitor_loop(self):
        while self._running:
            try:
                if self._main_window is None:
                    logger.warning("WeChat not initialized, skipping scan")
                else:
                    await self._check_new_messages()
                    self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Monitor error ({self._consecutive_errors}x): {e}")

            idx = min(self._consecutive_errors, len(_BACKOFF_SCHEDULE) - 1)
            await asyncio.sleep(_BACKOFF_SCHEDULE[idx])

    async def _check_new_messages(self):
        def scan(w):
            from pyweixin.utils import scan_for_new_messages
            with wechat_lock:
                result = scan_for_new_messages(main_window=w, close_weixin=False)
                return result

        loop = asyncio.get_event_loop()
        new_messages = await loop.run_in_executor(None, scan, self._main_window)

        if new_messages:
            logger.info(f"New messages from: {list(new_messages.keys())}")

        for sender, count in new_messages.items():
            if count > 0:
                content = await self._read_messages(sender)
                if content:
                    envelope = Envelope(
                        type=MessageType.USER_MESSAGE,
                        from_node=self.hub.assigned_id or "",
                        payload={
                            "session_id": sender,
                            "user_id": sender,
                            "content": content,
                            "message_type": "text",
                        },
                    )
                    await self.hub.send(envelope)

    async def _read_messages(self, sender: str) -> str:
        def read():
            with wechat_lock:
                try:
                    msg = _click_and_read(self._main_window, sender)
                    return msg
                except Exception as e:
                    logger.error(f"Read messages from {sender} failed: {type(e).__name__}: {e}")
                    return ""

        loop = asyncio.get_event_loop()
        # 12 秒超时，防止卡死
        task = loop.run_in_executor(None, read)
        try:
            return await asyncio.wait_for(task, timeout=12)
        except asyncio.TimeoutError:
            logger.error(f"Read messages from {sender} timed out (12s)")
            return ""


def _click_and_read(main_window, sender: str) -> str:
    """找 → 点 → 读消息"""
    import time as _time
    from pyweixin.Uielements import Lists, SideBar, Main_window, Texts

    # 1. 聚焦主窗口
    try:
        main_window.set_focus()
    except Exception:
        pass

    # 2. 确保在会话列表视图
    try:
        chats_btn = main_window.child_window(**SideBar.Weixin)
        if chats_btn.exists(timeout=0.5):
            chats_btn.click_input()
    except Exception:
        pass

    # 3. 获取会话列表
    session_list = main_window.child_window(**Main_window.SessionList)
    if not session_list.exists(timeout=1):
        logger.warning("Session list not found")
        return ""

    # 4. 在列表中找目标联系人
    items = session_list.children(control_type="ListItem")
    if not items:
        logger.warning("No session list items")
        return ""

    target_item = None
    for item in items:
        try:
            aid = item.automation_id().replace("session_item_", "")
            if aid == sender:
                target_item = item
                break
        except Exception:
            continue

    if target_item is None:
        logger.warning(f"Sender '{sender}' not found in visible session list")
        return ""

    # 5. 点击联系人打开聊天
    try:
        target_item.click_input()
    except Exception as e:
        logger.warning(f"Click {sender} failed: {e}")
        return ""

    # 6. 等待聊天区域出现，检查顶部名称确认打开正确
    _time.sleep(0.5)
    name_label = dict(Texts.CurrentChatNameText)
    name_label["title"] = sender
    current_chat = main_window.child_window(**name_label)
    if not current_chat.exists(timeout=2):
        logger.warning(f"Chat window for '{sender}' didn't open")
        return ""

    # 7. 读取消息气泡（CheckBox → ListItem 回退）
    chat_area = main_window.child_window(**Lists.FriendChatList)
    if not chat_area.exists(timeout=2):
        logger.warning("Chat message list not found")
        return ""

    bubbles = chat_area.children(control_type="CheckBox")
    if not bubbles:
        bubbles = chat_area.children(control_type="ListItem")
    if not bubbles:
        logger.warning(f"No message controls visible for {sender}")
        return ""

    texts = [b.window_text() for b in bubbles[-5:] if b.window_text().strip()]
    if not texts:
        return ""

    return "\n".join(texts)
