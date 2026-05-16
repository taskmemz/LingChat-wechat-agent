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
        # 启动时一次性获取微信主窗口
        loop = asyncio.get_event_loop()
        self._main_window = await loop.run_in_executor(None, self._init_weixin)
        logger.info(
            f"WeChat window initialized: {self._main_window is not None}"
        )
        asyncio.create_task(self._monitor_loop())
        logger.info("Monitor service started")

    def _init_weixin(self):
        with wechat_lock:
            from pyweixin.WeChatTools import Navigator

            try:
                main = Navigator.open_weixin(is_maximize=False)
                return main
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
                result = scan_for_new_messages(
                    main_window=w, close_weixin=False
                )
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
            import pyweixin.WeChatTools as wt
            from pyweixin.Uielements import Lists

            with wechat_lock:
                dialog = None
                try:
                    dialog = wt.Navigator.open_dialog_window(
                        friend=sender,
                        search_pages=1,
                        close_weixin=False,
                    )
                    chat_list = dialog.child_window(**Lists.FriendChatList)
                    if not chat_list.exists(timeout=1):
                        return ""
                    messages = chat_list.children(control_type="CheckBox")
                    if not messages:
                        return ""
                    texts = [m.window_text() for m in messages[-5:] if m.window_text().strip()]
                    return "\n".join(texts)
                except Exception as e:
                    logger.error(f"Read messages from {sender} failed: {e}")
                    return ""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, read)
